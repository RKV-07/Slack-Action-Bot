# Changelog — Local LLM Integration

## Overview
Converted the Slack bot from Google Gemini API to a local Qwen3-8B model running via llama.cpp server.

---

## v2.1 Updates (2026-07-12)

### Dual LLM Provider
- `LLM_PROVIDER=local|gemini` — user-selectable primary (default: local Qwen3)
- `LLM_FALLBACK_ENABLED=true` — automatic cross-fallback when primary fails
- `check_local_llm()` / `check_gemini_llm()` for `/sab test` diagnostics

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
graph/nodes.py (classify_intent — 12 routes)
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
