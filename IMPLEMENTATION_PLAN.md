# SAB Implementation Plan (v2.1) — COMPLETED

**Status: Implemented 2026-07-12** — 195 tests passing, 10/10 bug checks PASS.

Use this file if you need to re-apply or verify changes manually.

**Project root:** `Slack-Action-Bot/`

**Verify when done:**
```bash
cd Slack-Action-Bot
uv run pytest test_all.py test_e2e.py -v
uv run main.py   # smoke test
```

---

## Checklist Overview

- [ ] Step 1: Bug tests (verify already-fixed + new)
- [ ] Step 2: Fix learn MCP footer (`learn_via_mcp`)
- [ ] Step 3: Fix reminder text (`me to` strip)
- [ ] Step 4: Codereview LLM failure disclosure
- [ ] Step 5: Dual LLM (local + gemini + cross-fallback)
- [ ] Step 6: Duplicate issue detection
- [ ] Step 7: Release notes generator
- [ ] Step 8: Daily digest
- [ ] Step 9: Semgrep optional dep
- [ ] Step 10: Update all docs + help text
- [ ] Step 11: Run full test suite

---

## Already Fixed (do NOT re-break)

These are **already in the codebase** — only add tests to confirm:

| Bug | File | What to verify |
|-----|------|----------------|
| Double-underscore footer | `services/codereview_service.py:321` | `source_note = "via GitHub MCP"` (no `_` in constant) |
| Risk score regex | `services/codereview_service.py:303-313` | `re.search(r'risk level.{0,20}high', text_lower)` on full text |
| Thread-safe state | `graph/state.py` | `review_via_mcp`, `review_semgrep_findings` in BotState |
| Reminder cancel | `graph/nodes.py:311-330` | `.strip('`<>')` + `reminder_` prefix |
| LLM error body | `services/llm_service.py:78` | logs `resp.text[:300]` |
| MCP no-files fallback | `services/codereview_service.py:61-71` | falls through to direct API |
| No-diff warning | `graph/nodes.py:585-590` | sets `review_warning` |

---

## Step 1: Add Bug Tests

**File:** `test_all.py`

Add these test classes:

```python
class TestRiskScore:
    def test_high_risk_past_200_chars(self):
        from services.codereview_service import _risk_score
        text = "x" * 300 + "Risk Level: High"
        assert _risk_score(text) == "🔴 High"

    def test_semgrep_error_is_high(self):
        from services.codereview_service import _risk_score
        findings = [{"severity": "ERROR"}]
        assert _risk_score("no issues", findings) == "🔴 High"

    def test_low_default(self):
        from services.codereview_service import _risk_score
        assert _risk_score("Risk Level: Low") == "🟢 Low"


class TestMergeReviewsFormatting:
    def test_footer_no_double_underscore(self):
        from services.codereview_service import merge_reviews
        out = merge_reviews("sec", "perf", "best", {"title": "T"}, via_mcp=True)
        assert "_via GitHub MCP_" in out
        assert "__" not in out.split("Review generated")[-1]
```

---

## Step 2: Fix Learn MCP Footer

### 2a. `graph/state.py`

Add to `BotState` Literal and fields:
```python
command_type: Literal[
    ..., "digest", "duplicate", "release_notes",  # add with step 6-8
]
learn_via_mcp: bool
```

For now (step 2 only), add:
```python
learn_via_mcp: bool
```

### 2b. `handlers/shared.py` — `build_initial_state`

Add:
```python
"learn_via_mcp": False,
```

### 2c. `graph/nodes.py` — `learn_research`

After `result = research_topic(topic)`:
```python
state["learn_resources"] = result.get("resources", [])
state["learn_via_mcp"] = result.get("search_via_mcp", False)
```

### 2d. `graph/nodes.py` — `learn_resources`

Change:
```python
summary = curate_resources(topic, resources, path)
```
To:
```python
summary = curate_resources(
    topic, resources, path,
    search_via_mcp=state.get("learn_via_mcp", False),
)
```

### 2e. `services/learn_service.py` — fallback path (~line 208)

Add footer to the non-LLM fallback return:
```python
source_note = "via GitHub MCP" if search_via_mcp else "via GitHub REST API (fallback)"
return (
    f"**Learning Path: {topic}**\n\n"
    ...
    f"\n\n_{source_note}_"
)
```

---

## Step 3: Fix Reminder Text

**File:** `graph/nodes.py` — `parse_reminder`, dateparser branch (~line 252-257)

After the existing time-phrase strip, add:
```python
reminder_text = re.sub(
    r'^\s*(me\s+to\s+|to\s+)', '', reminder_text, flags=re.IGNORECASE
).strip()
```

**Test:** `remind me to call boss tomorrow at 3pm` → text should be `call boss`, not `me to call boss`.

---

## Step 4: Codereview LLM Failure Disclosure

**File:** `services/codereview_service.py`

### 4a. Add constants at top:
```python
_FALLBACK_SECURITY = "Security review completed - no major issues found."
_FALLBACK_PERFORMANCE = "Performance review completed - no major issues found."
_FALLBACK_BEST = "Best practices review completed - code looks good."
```

Use these in `review_security`, `review_performance`, `review_best_practices` return statements.

### 4b. Update `merge_reviews`:

```python
def merge_reviews(security, performance, best_practices, pr_data, via_mcp=False, semgrep_findings=None):
    ...
    warnings = []
    fallbacks = sum([
        security.strip() == _FALLBACK_SECURITY,
        performance.strip() == _FALLBACK_PERFORMANCE,
        best_practices.strip() == _FALLBACK_BEST,
    ])
    if fallbacks >= 2:
        warnings.append(
            "⚠️ LLM unavailable — partial or placeholder review below. "
            "Check llama-server (-c 16384) or set LLM_PROVIDER=gemini."
        )
    files = pr_data.get("files", [])
    if len(files) > 5:
        warnings.append(f"ℹ️ Reviewed 5 of {len(files)} changed files (diff truncated).")

    prefix = "\n".join(warnings) + "\n\n" if warnings else ""
    ...
    return prefix + "\n".join(sections)
```

---

## Step 5: Dual LLM Provider

### 5a. `config.py`

```python
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "local").lower()
LLM_FALLBACK_ENABLED = os.environ.get("LLM_FALLBACK_ENABLED", "true").lower() == "true"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
```

### 5b. `.env.example`

```env
LLM_PROVIDER=local
LLM_FALLBACK_ENABLED=true
GOOGLE_API_KEY=your-google-api-key
GEMINI_MODEL=gemini-2.0-flash
LLAMA_PARALLEL=4
TAVILY_API_KEY=tvly-...
```

Remove `DEFAULT_GITHUB_REPO` line.

### 5c. `services/llm_service.py`

Refactor into three functions:

```python
from config import LLAMA_BASE_URL, LLM_PROVIDER, LLM_FALLBACK_ENABLED, GOOGLE_API_KEY, GEMINI_MODEL

def _local_completion(user_msg, max_tokens=500, system_msg=None) -> str:
    # Move existing _chat_completion body here (llama-server POST)
    ...

def _gemini_completion(user_msg, max_tokens=500, system_msg=None) -> str:
    if not GOOGLE_API_KEY:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json"}
    parts = []
    if system_msg:
        parts.append({"text": system_msg})
    parts.append({"text": user_msg})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    try:
        resp = requests.post(url, headers=headers, params={"key": GOOGLE_API_KEY}, json=payload, timeout=90)
        if resp.status_code != 200:
            print(f"[LLM] Gemini error: HTTP {resp.status_code} - {resp.text[:300]}")
            return ""
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts_out = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts_out)
        return text.strip()
    except Exception as e:
        print(f"[LLM] Gemini error: {e}")
        return ""

def _chat_completion(user_msg, max_tokens=500, system_msg=None) -> str:
    primary = LLM_PROVIDER if LLM_PROVIDER in ("local", "gemini") else "local"
    fn = _local_completion if primary == "local" else _gemini_completion
    result = fn(user_msg, max_tokens, system_msg)
    if result:
        return result
    if not LLM_FALLBACK_ENABLED:
        return ""
    fallback_fn = _gemini_completion if primary == "local" else _local_completion
    can_fallback = (primary == "local" and GOOGLE_API_KEY) or (primary == "gemini")
    if not can_fallback:
        return ""
    print(f"[LLM] Primary {primary} failed, falling back to {'gemini' if primary == 'local' else 'local'}")
    return fallback_fn(user_msg, max_tokens, system_msg)
```

### 5d. `graph/nodes.py` — `test_llm_connection`

Update to show:
```
Provider: local (primary) · Fallback: enabled
✓ Local LLM · ✓ Gemini (fallback ready)
```

Test both providers with a quick `_chat_completion("Say OK", max_tokens=5)` when key is set.

---

## Step 6: Duplicate Issue Detection

### 6a. `services/github_service.py`

```python
import difflib

def find_similar_issues(repo: str, new_title: str, threshold: float = 0.55, count: int = 50) -> list[dict]:
    issues = fetch_repo_issues(repo, count=count)
    scored = sorted(
        ((difflib.SequenceMatcher(None, new_title.lower(), i["title"].lower()).ratio(), i) for i in issues),
        key=lambda x: -x[0],
    )
    return [{"score": round(s, 2), **i} for s, i in scored if s >= threshold][:3]
```

### 6b. `graph/state.py`

Add `"duplicate"` to `command_type` Literal.

### 6c. `graph/nodes.py` — `classify_intent`

```python
if re.match(r'^duplicate\b', raw_lower):
    state["command_type"] = "duplicate"
    return state
```

### 6d. `graph/nodes.py` — new node

```python
def duplicate_check_node(state: BotState) -> BotState:
    raw = state.get("raw_input", "")
    repo = extract_repo_from_text(raw)
    title_match = re.search(r'"([^"]+)"', raw) or re.search(r"'([^']+)'", raw)
    if not repo or not title_match:
        state["response_message"] = (
            "Usage: `/sab duplicate owner/repo \"issue title to check\"`"
        )
        return state
    matches = find_similar_issues(repo, title_match.group(1))
    if not matches:
        state["response_message"] = f"No likely duplicates found in `{repo}`."
        return state
    lines = [f"*Possible duplicates in {repo}:*"]
    for m in matches:
        pct = int(m["score"] * 100)
        lines.append(f"• {pct}% — \"{m['title']}\" <{m['url']}|#{m['number']}>")
    state["response_message"] = "\n".join(lines)
    return state
```

### 6e. `graph/workflow.py`

- Add node `duplicate_check`
- Route `"duplicate": "duplicate_check"` in `route_after_classification`
- Edge `duplicate_check` → END

---

## Step 7: Release Notes Generator

### 7a. `services/github_service.py`

```python
def fetch_merged_prs(repo: str, count: int = 15) -> list[dict]:
    if not GITHUB_TOKEN:
        return []
    url = f"{_GITHUB_API}/repos/{repo}/pulls"
    params = {"state": "closed", "per_page": count, "sort": "updated", "direction": "desc"}
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        if resp.status_code == 200:
            return [
                {"title": p["title"], "number": p["number"], "url": p["html_url"]}
                for p in resp.json() if p.get("merged_at")
            ]
    except requests.RequestException as e:
        print(f"[GitHub] fetch_merged_prs failed: {e}")
    return []
```

### 7b. `services/release_service.py` (new file)

```python
from services.github_service import fetch_merged_prs
from services.llm_service import _chat_completion

def generate_release_notes(repo: str) -> str:
    prs = fetch_merged_prs(repo)
    if not prs:
        return f"No recently merged PRs found for `{repo}`."
    pr_list = "\n".join(f"- {p['title']} (#{p['number']})" for p in prs)
    result = _chat_completion(
        f"Generate concise release notes from these merged PRs, grouped under "
        f"Features / Fixes / Other:\n\n{pr_list}",
        max_tokens=500,
        system_msg="You write clear, grouped release notes from PR titles.",
    )
    return result or f"Could not generate release notes for `{repo}` (LLM unavailable)."
```

### 7c. `graph/nodes.py`

```python
# classify_intent:
if re.search(r'\brelease\s+notes?\b', raw_lower):
    state["command_type"] = "release_notes"
    return state

def release_notes_node(state: BotState) -> BotState:
    from services.release_service import generate_release_notes
    repo = extract_repo_from_text(state.get("raw_input", ""))
    if not repo:
        state["response_message"] = "Usage: `/sab release notes owner/repo`"
        return state
    state["response_message"] = generate_release_notes(repo)
    return state
```

### 7d. `graph/workflow.py`

Add `"release_notes"` route → `release_notes_node` → END.

---

## Step 8: Daily Digest

### 8a. `services/reminder_service.py`

```python
from services.github_service import fetch_latest_issues, fetch_latest_prs
from datetime import datetime, timedelta

def schedule_daily_digest(channel_id: str, hour: int = 9, minute: int = 0):
    _ensure_scheduler()
    scheduler.add_job(
        _post_daily_digest, "cron", hour=hour, minute=minute,
        args=[channel_id], id=f"digest_{channel_id}", replace_existing=True,
    )

def schedule_digest_demo(channel_id: str, delay_minutes: int = 2):
    _ensure_scheduler()
    run_date = datetime.now() + timedelta(minutes=delay_minutes)
    scheduler.add_job(
        _post_daily_digest, "date", run_date=run_date,
        args=[channel_id], id=f"digest_demo_{channel_id}", replace_existing=True,
    )

def cancel_daily_digest(channel_id: str) -> bool:
    _ensure_scheduler()
    try:
        scheduler.remove_job(f"digest_{channel_id}")
        return True
    except Exception:
        return False

def _post_daily_digest(channel_id: str):
    client = _get_client()
    issues = fetch_latest_issues(count=5)
    prs = fetch_latest_prs(count=5)
    lines = ["*📅 Daily Digest*", "", "*Issues:*"]
    lines += [f"• <{i['url']}|{i['title']}>" for i in issues] or ["  (none)"]
    lines += ["", "*PRs:*"]
    lines += [f"• <{p['url']}|{p['title']}>" for p in prs] or ["  (none)"]
    try:
        client.chat_postMessage(channel=channel_id, text="\n".join(lines))
    except Exception as e:
        print(f"[Digest] Failed to post: {e}")
```

### 8b. `graph/nodes.py`

```python
# classify_intent:
if re.match(r'^digest\b', raw_lower):
    state["command_type"] = "digest"
    return state

def digest_node(state: BotState) -> BotState:
    from services.reminder_service import schedule_daily_digest, cancel_daily_digest, schedule_digest_demo
    raw = state.get("raw_input", "").lower()
    channel_id = state.get("channel_id", "")
    if "unsubscribe" in raw or "cancel" in raw:
        ok = cancel_daily_digest(channel_id)
        state["response_message"] = "Daily digest cancelled." if ok else "No digest was subscribed for this channel."
    elif "demo" in raw:
        schedule_digest_demo(channel_id, delay_minutes=2)
        state["response_message"] = "Demo digest scheduled — posting in ~2 minutes."
    elif "subscribe" in raw:
        schedule_daily_digest(channel_id)
        state["response_message"] = "Daily digest subscribed — posts at 9:00 UTC in this channel."
    else:
        state["response_message"] = "Usage: `/sab digest subscribe`, `digest unsubscribe`, or `digest demo`"
    return state
```

### 8c. `graph/workflow.py`

Add `"digest"` route → `digest_node` → END.

---

## Step 9: Semgrep Optional Dep

**File:** `pyproject.toml`

```toml
[dependency-groups]
dev = ["pytest>=9.1.1"]
optional = ["semgrep>=1.0.0"]
```

Install: `uv sync --group optional`

---

## Step 10: Update Docs

### Files to update:

1. **README.md** — add to Features table:
   - Daily Digest: `/sab digest subscribe`
   - Duplicate check: `/sab duplicate owner/repo "title"`
   - Release notes: `/sab release notes owner/repo`
   - Dual LLM: `LLM_PROVIDER`, `LLM_FALLBACK_ENABLED`

2. **DESIGN.md** — add intent routes for digest/duplicate/release_notes; dual LLM flow diagram; `learn_via_mcp` in BotState

3. **CHANGELOG.md** — new section:
   ```markdown
   ## v2.1 (2026-07-12)
   ### Features
   - Dual LLM: LLM_PROVIDER=local|gemini with cross-fallback
   - Daily digest, duplicate detection, release notes
   ### Bug Fixes
   - learn_via_mcp footer, reminder text cleanup, LLM failure disclosure
   ```

4. **CHANGES.md** — mirror v2.1

5. **graph/nodes.py** `build_help_response` — add 3 new command sections

6. **Root CHANGELOG.md** — pointer to Slack-Action-Bot/CHANGELOG.md v2.1

---

## Step 11: New Tests + Full Suite

Add to `test_all.py`:

```python
class TestLearnViaMcp:
    @patch("graph.nodes.research_topic")
    def test_flag_threaded(self, mock_research):
        mock_research.return_value = {"resources": [], "search_via_mcp": True}
        from graph.nodes import learn_research, learn_resources
        state = {"learn_topic": "python", "response_message": "", "learn_resources": [], "learn_path": {}}
        state = learn_research(state)
        assert state["learn_via_mcp"] is True

class TestLLMProvider:
    @patch("services.llm_service._local_completion", return_value="")
    @patch("services.llm_service._gemini_completion", return_value="gemini ok")
    @patch("services.llm_service.LLM_PROVIDER", "local")
    @patch("services.llm_service.LLM_FALLBACK_ENABLED", True)
    @patch("services.llm_service.GOOGLE_API_KEY", "key")
    def test_cross_fallback(self, mock_gemini, mock_local):
        from services.llm_service import _chat_completion
        assert _chat_completion("hi") == "gemini ok"
```

Add E2E in `test_e2e.py` for `digest subscribe`, `duplicate owner/repo "title"`, `release notes owner/repo`.

**Run:**
```bash
uv run pytest test_all.py test_e2e.py -v
```

Expected: all 176+ tests pass.

---

## Demo Commands (manual smoke test)

```text
/sab test
/sab codereview owner/repo#3
/sab learn python async
/sab duplicate owner/repo "fix login bug"
/sab release notes owner/repo
/sab digest demo
/sab remind me to call boss tomorrow at 3pm
/sab reminders
/sab reminder cancel <id>
```

---

## Environment Setup (not code)

```bash
# llama-server (local primary)
llama-server -m models/qwen3-8b-q4_k_m.gguf --port 8080 --parallel 4 -c 16384

# semgrep
uv sync --group optional

# invite bot to test channel
/invite @YourBotName

# .env for safe demo
LLM_PROVIDER=local
LLM_FALLBACK_ENABLED=true
GOOGLE_API_KEY=your-key
```

---

## Out of Scope

- Real-Time Search API (needs Slack scope reinstall)
- Removing GOOGLE_API_KEY (keep it)

---

## File Touch Summary

| File | Steps |
|------|-------|
| `config.py` | 5 |
| `.env.example` | 5, 10 |
| `services/llm_service.py` | 5 |
| `services/codereview_service.py` | 4 |
| `services/learn_service.py` | 2 |
| `services/github_service.py` | 6, 7 |
| `services/release_service.py` | 7 (new) |
| `services/reminder_service.py` | 8 |
| `graph/state.py` | 2, 6, 7, 8 |
| `graph/nodes.py` | 2, 3, 5, 6, 7, 8, 10 |
| `graph/workflow.py` | 6, 7, 8 |
| `handlers/shared.py` | 2 |
| `pyproject.toml` | 9 |
| `test_all.py` | 1, 11 |
| `test_e2e.py` | 11 |
| `README.md`, `DESIGN.md`, `CHANGELOG.md`, `CHANGES.md` | 10 |
