# Changelog — Local LLM Integration

## Overview
Converted the Slack bot from Google Gemini API to a local Qwen3-8B model running via llama.cpp server.

---

## v2.1 Updates (2026-07-12)

### Dual LLM Provider
- `LLM_PROVIDER=local|gemini|remote` — user-selectable primary (default: local Qwen3)
- `LLM_FALLBACK_ENABLED=true` — automatic cross-fallback when primary fails
- `check_local_llm()` / `check_gemini_llm()` / `check_remote_llm()` for `/sab test` diagnostics
- Fallback chain: local → remote (qwen3.5-397b / glm-5.2) → gemini

### Remote LLM (glm-5.2 / qwen3.5-397b)
- OpenAI-compatible endpoint via [lucky-cat-api](https://github.com/KHROTU/lucky-cat-api)
- `REMOTE_LLM_BASE_URL=http://127.0.0.1:8000`
- `REMOTE_LLM_MODEL=glm-5.2` (200k context, great for coding/GitHub) or `qwen3.5-397b-a17b` (266k context)
- Install: `uv sync --group remote-llm` (adds selenium, fastapi, uvicorn)
- Start: `python lc_server.py` or `uvicorn lc_server:app --host 127.0.0.1 --port 8000`
- Fallback: if remote unavailable, bot falls back to local Qwen3 → gemini`

### LLM Context Size Boot Check
- `check_llm_context_size()` verifies llama-server has ≥16384 tokens at boot
- Calls `GET /props` endpoint to read `n_ctx` from running server
- Warns loudly if `-c` flag is missing — prevents silent HTTP 400 cascading failures
- Called once in `main.py` `start()` before MCP init
- Restart llama-server with `-c 16384`:
  ```bash
  cd ~/llama.cpp
  ./build/bin/llama-server \
    -m <path-to>/Qwen3-8B-Q4_K_M.gguf \
    -ngl 999 \
    -c 16384 \
    --parallel 4 \
    --host 0.0.0.0 \
    --port 8080
  ```

### New Commands
- `/sab digest subscribe|unsubscribe|demo` — daily GitHub digest via APScheduler cron
- `/sab duplicate owner/repo "title"` — difflib similarity over open issues
- `/sab release notes owner/repo` — LLM-grouped notes from merged PRs

### Bug Fixes
- `learn_via_mcp` threaded through BotState (MCP footer in /learn)
- Reminder text strips `"me to"` / `"to"` connector words
- Codereview LLM failure warning when 2+ reviewers return fallback strings
- File truncation disclosure for large PRs


### Before
- Used `langchain-google-genai` with Gemini API
- Required `GOOGLE_API_KEY`

### After
- Uses direct HTTP requests to llama-server (OpenAI-compatible API)
- No API key needed
- `/no_think` prefix disables Qwen3 thinking mode
- `reasoning_content` fallback for Qwen3's split output
- `PERSONA` constant with anti-stall and anti-invention instructions
- `_chat_completion()` null-guards malformed responses

---

## Config (`config.py`)

```python
LLAMA_BASE_URL = os.environ.get("LLAMA_BASE_URL", "http://localhost:8080")
LLAMA_PARALLEL = os.environ.get("LLAMA_PARALLEL")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
```

---

## Architecture

```
User mention
       ▼
handlers/events.py (strips mention tag, dedup guard on event_ts)
       ▼
graph/workflow.py (LangGraph StateGraph)
       ▼
graph/nodes.py (classify_intent — 15 routes)
       ▼
┌─────────────────────────────────────┐
│ greeting? → build_greeting_response │
│ help?     → build_help_response     │
│ test_llm? → test_llm_connection     │
│           (LLM + 3 MCP health check)│
│ reminder? → parse_reminder          │
│ reminders → list / cancel           │
│ github?   → extract_github          │
│ context?  → summarize_action        │
│ learn?    → learn_research          │
│ codereview→ codereview_fetch        │
│ chat?     → build_chat_response     │
└─────────────────────────────────────┘
       ▼
services/llm_service.py (_chat_completion)
       ▼
llama-server (Qwen3-8B) /no_think
       ▼
Response to Slack
```

---

## How to Test

### System Diagnostics
`/sab test` — checks LLM + all 3 MCP sessions

### LLM Context Size Check
At boot, `check_llm_context_size()` calls `GET /props` on llama-server and warns if context is too small:
```
[LLM] Context size: 16384 tokens (OK)
```
If you see a warning, restart llama-server with `-c 16384`:
```bash
cd ~/llama.cpp
./build/bin/llama-server \
  -m <path-to>/Qwen3-8B-Q4_K_M.gguf \
  -ngl 999 \
  -c 16384 \
  --parallel 4 \
  --host 0.0.0.0 \
  --port 8080
```

### Greetings
`hi`, `hey`, `hello`, `what can you do`

### Reminders
```
/sab -r "Check PR" @30m
/sab remind me to check server tomorrow at 3pm
/sab reminders
/sab reminder cancel <id>
```

### Summarize
Mention bot in a thread, or `/sab summarize` in a channel

### GitHub
`owner/repo#123`, paste a GitHub URL, `/sab latest issues`

### Code Review
`/sab codereview owner/repo#123` (or paste a PR URL)

### Learn
`/sab learn python async programming`

---

## Thread-Safety & Formatting Fixes

### Date: 2026-07-08

### Thread-Safe State Threading

Module-level globals (`_last_fetch_via_mcp`, `_last_semgrep_findings`, `_last_search_via_mcp`) replaced with return values threaded through BotState:

| Old (Global) | New (State Field) |
|---|---|
| `_last_fetch_via_mcp` | `review_via_mcp: bool` |
| `_last_semgrep_findings` | `review_semgrep_findings: list` |
| `_last_search_via_mcp` | Passed as parameter to `curate_resources` |

**Why:** `ThreadPoolExecutor(max_workers=5)` allows concurrent commands. Globals cross-contaminate under concurrent load (e.g., two `/sab codereview` calls).

### `md_to_slack_mrkdwn` Bare URL Handling

```python
# Before: only converted [text](url) format
# After: wraps bare http(s):// URLs in <url> syntax
text = re.sub(r'(?<!<)(https?://[^\s<>]+)', r'<\1>', text)
```

Bare URLs now auto-link in Slack without double-wrapping already-linked URLs.

### Reminder Cancel Cleanup

```python
# Before: raw \S+ capture included stray <, >, backticks
# After: captures [a-zA-Z0-9_<>]+, then .strip('`<>')
match = re.search(r'(?:cancel|delete|remove)\s+([a-zA-Z0-9_<>`]+)', raw, re.IGNORECASE)
if match:
    job_id = match.group(1).strip('`<>')
    if not job_id.startswith("reminder_"):
        job_id = f"reminder_{job_id}"
```

Short suffixes (e.g., `abc123`) auto-prefix to `reminder_abc123`.

### Files Changed

| File | Changes |
|---|---|
| `services/codereview_service.py` | Removed `_last_fetch_via_mcp`, `_last_semgrep_findings` globals; `_github_get_pr` returns `via_mcp` in dict; `review_security` accepts `semgrep_findings` param; `_risk_score` accepts `semgrep_findings` param; `merge_reviews` accepts `via_mcp` and `semgrep_findings` params |
| `services/learn_service.py` | Removed `_last_search_via_mcp` global; `_github_search_repos` returns `{"via_mcp": bool, "repos": list}`; `research_topic` returns `search_via_mcp`; `curate_resources` accepts `search_via_mcp` param |
| `graph/state.py` | Added `review_via_mcp: bool`, `review_semgrep_findings: list` to BotState |
| `graph/nodes.py` | `codereview_fetch` stores `via_mcp` in state; `codereview_security` runs Semgrep and stores findings in state; `codereview_merge` passes `via_mcp` and `semgrep_findings` to `merge_reviews`; `reminder_cancel_node` strips stray characters |
| `handlers/shared.py` | `md_to_slack_mrkdwn` handles bare URLs; `build_initial_state` includes new fields |

---

## MCP Timeout & Reliability Fixes

### Date: 2026-07-12

### Split Timeouts: Connect vs Tool Calls

One timeout (30s) was used for two different operations — cold-start connect (can take 60-120s for npx/uvx installs) and per-request tool calls (should be fast). Now split:

| Operation | Before | After |
|---|---|---|
| Cold-start connect (`connect()`) | 30s | **90s** |
| Tool call (`call_tool()`) | 30s | **20s** |

`connect()` now returns `bool` — callers check if actually connected instead of printing blindly.

### Semgrep Pinned Ruleset

`--config=auto` triggers a network call to Semgrep's rule registry on every invocation. Changed to `--config=p/security-audit` — no registry lookup, ~5s faster, more reliable.

### GitHub Cache Stampede Fix

`fetch_all_repos()` was TTL-cached but not lock-protected. Two near-simultaneous commands could both miss the cache and double-hit GitHub. Added `threading.Lock()` to `@cached` decorator.

### LLM 503 Retry

On boot, llama-server returns 503 "model still loading" for the first few seconds. Now retries once with 3s sleep instead of failing immediately.

### Public Repo Access Without Token

Removed `if not GITHUB_TOKEN: return None` guards from `fetch_github_issue`, `fetch_repo_issues`, `fetch_repo_prs`. Public repos work fine without a token (60 req/hr unauthenticated). Private repos get a 404 with a hint to set `GITHUB_TOKEN`.

### Files Changed

| File | Changes |
|---|---|
| `services/mcp_client.py` | `_CONNECT_TIMEOUT=90`, `_CALL_TIMEOUT=20`; `_run_async` accepts timeout param; `connect()` returns bool; `setup_mcp_servers` checks result |
| `services/codereview_service.py` | `--config=auto` → `--config=p/security-audit`; timeout 25→30 |
| `services/github_service.py` | Added `threading.Lock` to cache; removed token guards for public repos; 404 hint |
| `services/llm_service.py` | Added `import time`; retry once on 503 with 3s sleep |

---

## Real-Time Search Routing Fix

### Date: 2026-07-12

### Missing Route: `"search": "search"` in `route_after_classification`

`classify_intent` correctly set `command_type = "search"`, but `route_after_classification`'s `routes` dict had no matching key. `.get(cmd, "help_response")` silently fell back to help every time — search never actually ran.

**One-line fix in `graph/workflow.py`:**
```python
routes = {
    ...
    "release_notes": "release_notes",
    "search": "search",  # ← was missing
}
```

This was the real reason `@bot find discussions about X` returned the help menu — not scopes, not Assistant toggle, not auth. The search code was correct all along; it just never got called.

### Files Changed

| File | Changes |
|---|---|
| `graph/workflow.py` | Added `"search": "search"` to `route_after_classification` |

---

## Real-Time Search Feature

### Date: 2026-07-08

### New Service: `services/slack_search_service.py`

Implements cross-channel search via Slack's `assistant.search.context` API.

**Key design:**
- Bot token in Authorization header, `action_token` in request body (per Slack docs)
- Graceful fallback when `action_token` is missing (explains required scopes)
- Handles `missing_scope` and `invalid_action_token` errors specifically
- LLM summarizes search results with context messages

**Required Slack scopes:**
- `search:read.public` — search public channels
- `search:read.files` — search files
- `search:read.users` — search users

**Command routing:**
- `/sab search <query>` — direct search command
- `@bot find discussions about X` — natural language search via app_mention
- Both routes use `action_token` from event payload

### Files Changed

| File | Changes |
|---|---|
| `services/slack_search_service.py` | **New** — `search_slack_context()` and `summarize_search_results()` |
| `graph/state.py` | Added `"search"` to command_type literal; `action_token`, `search_query` fields |
| `graph/nodes.py` | `classify_intent` routes `search` and `find discussions about`; `search_node` calls service |
| `graph/workflow.py` | `search_node` imported and wired |
| `handlers/events.py` | Passes `action_token=event.get("action_token", "")` to state |
| `handlers/shared.py` | `build_initial_state` accepts `action_token` param |
