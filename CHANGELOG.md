# Changelog

## v2.1 — Dual LLM, New Features, Bug Fixes (2026-07-12)

### New Features
- **Dual LLM provider**: `LLM_PROVIDER=local|gemini` with `LLM_FALLBACK_ENABLED` cross-fallback (local Qwen3 primary, Gemini safety net)
- **Daily digest**: `/sab digest subscribe|unsubscribe|demo` — proactive GitHub issues/PRs via APScheduler cron
- **Duplicate detection**: `/sab duplicate owner/repo "title"` — difflib similarity over open issues
- **Release notes**: `/sab release notes owner/repo` — LLM-grouped notes from merged PRs
- **Real-Time Search**: `/sab search <query>` or `@bot find discussions about X` — cross-channel search via Slack RTS API
- **MCP integration**: 3 MCP servers (GitHub, Fetch, custom Slack) with AsyncExitStack, background loop, split timeouts
- **Semgrep grounding**: Real static analysis in security reviews with pinned ruleset
- **Public repo access**: GitHub lookups work without `GITHUB_TOKEN` for public repos

### Bug Fixes
- Learn MCP footer always showed REST fallback — `learn_via_mcp` now threaded through BotState
- Natural-language reminder text left `"me to"` connector words — stripped in dateparser branch
- Codereview showed fake reviews when LLM failed — visible warning banner when 2+ fallback strings detected
- File truncation disclosure when reviewing large PRs (5 of N files)
- Semgrep added as optional dependency group in pyproject.toml

### Tests
- 20+ new unit/E2E tests for risk score, footer formatting, LLM provider, and new commands
- Updated `test_no_token_returns_none` — public repos now work without token
- Fixed `route_after_classification` tests for duplicate/digest/search/release_notes routes
- Added `md_to_slack_mrkdwn` tests (bold, links, bare URLs, double-wrap safety)
- Added `build_initial_state` tests for `action_token` and `search_query` fields
- Added `search_node`, `digest_node`, `duplicate_check_node`, `release_notes_node` unit tests
- Added `TestE2ESearch` end-to-end tests (empty query, results, error, natural language, action_token)
- All **225 tests passing** (168 unit + 57 e2e)

---

## v2.0 — Full Feature Set (2026-07-11)

### New Features

#### Local LLM (Qwen3-8B)
- Migrated from Google Gemini API to local llama-server
- `/no_think` prefix disables Qwen3 thinking mode for faster responses
- `reasoning_content` fallback for Qwen3's split output format
- `PERSONA` constant with anti-stall instructions
- `LLAMA_PARALLEL=4` for concurrent reviewer subagents

#### Code Review (`/sab codereview`)
- 3-subagent fan-out: Security, Performance, Best Practices
- Semgrep grounding for real static analysis in security reviews (installed in uv)
- PR risk score (🔴/🟡/🟢) from Semgrep findings + LLM analysis
- Prompt truncation (3000 char cap) to fit Qwen3 context window per slot
- MCP fallback: when MCP returns no files, falls through to direct API
- `parse_review_ref` handles `owner/repo#N`, PR URLs, and bare repos
- Actionable error for bare repo URLs without PR number
- MCP source-transparency footer on every review
- Typo-tolerant via difflib (`coderview`, `review`, `pr`)

#### Learning Paths (`/sab learn`)
- 3-agent pipeline: Research → Structure → Resources
- Tavily search API for real, verified URLs
- GitHub repo search via MCP or direct API
- LLM prompt constrained to prevent hallucinated links

#### Reminders
- SQLite-persisted via APScheduler jobstore (`reminders.db`)
- List reminders: `/sab reminders`
- Cancel reminders: `/sab reminder cancel <id>`
- Natural language via dateparser (`tomorrow at 3pm`)
- Pre-normalization for "X mins later" phrasing

#### System Diagnostics (`/sab test`)
- Checks LLM connection + all 3 MCP sessions (GitHub, Fetch, Slack)
- Hint text on failure to guide debugging

#### MCP Integration
- GitHub MCP server (`@modelcontextprotocol/server-github`)
- Fetch MCP server (`mcp-server-fetch`)
- Custom Slack MCP server (in-repo, stdio transport)
- AsyncExitStack with background event loop
- Thread-safe sync facade with `_evict_session()`

#### Summarize
- Channel-level and thread-level message summarization
- Unified `is_real_message()` filter across all fetch paths
- `fetch_channel_messages` normalized to oldest-first ordering
- Configurable `SLACK_SUMMARY_MAX_MESSAGES` (default 25)
- Anti-hallucination prompt with minimum-message floor

#### GitHub Integration
- `fetch_all_repos()` with 2-min TTL cache
- `fetch_latest_issues()` / `fetch_latest_prs()` with early-exit
- Rate-limit tracking via `X-RateLimit-Remaining` headers
- Bare `#123` dropped (no default repo exists)
- GitHub URL routing (`/pull/` → codereview, `/issues/` → github)

### Bug Fixes

#### Critical
- `body: null` crash → `(x.get("body") or default)[:N]` across 10 instances
- Retry guard used wrong API → `context.get("retry_num")` instead of `event.get("headers")`
- `fetch_channel_messages` returned newest-first → added `.reverse()`
- `on_message`/`app_mention` handlers missing `context` arg → added for retry guard

#### Serious
- "what can you do" misrouted to greeting → separate `HELP_PHRASES` check
- `codereview` typo fell to chat → difflib fuzzy matching
- Summarize regex too strict → loose match catches typos
- `structure_learning_path` crashed on empty LLM response
- `_chat_completion` null-guarded for malformed responses

#### Moderate
- Bot messages included in summarize counts → `is_real_message()` filter
- Over-fetch +40 buffer to compensate for filtered bot messages
- Channel fetch hardcoded `count=6` → now uses `SLACK_SUMMARY_MAX_MESSAGES`
- Empty summarize message now explains why (bot replies, not human conversation)
- Slack MCP subprocess received full env → scoped to `SLACK_BOT_TOKEN` only
- `on_message`/`app_mention` handlers missing `event_ts` dedup → keyed on `event_ts`
- Bot sent broken Markdown to Slack (`**bold**`, `[text](url)`) → `md_to_slack_mrkdwn()` conversion
- `conversations_history`/`conversations_replies` had no rate-limit retry → `_call_with_backoff()`
- `not_in_channel` crash on /sab → catches SlackApiError, DMs user as fallback
- Reviewer prompts too large for Qwen3 context → truncated to 3000 chars

#### Minor
- BotState `command_type` Literal missing `reminder_list`/`reminder_cancel`
- `extract_repo_from_text` rejects dot-prefixed segments
- `detect_github_refs` drops bare `#123`

### Tests
- 168 unit tests + 57 end-to-end tests = **225 passing**
- Coverage: classify_intent, github_service, codereview_service, llm_service, learn_service, reminder_service, mcp_slack_server, slack_summarize_service, graph nodes, workflow, handlers, search_node, digest_node, duplicate_check_node, release_notes_node

---

## v1.0 — Initial Build (2026-07-08)

### Bug Fix Pass: 17 Issues Resolved

See original CHANGELOG.md for the initial 17-bug audit.

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 3 | All fixed |
| SERIOUS | 6 | All fixed |
| MODERATE | 5 | All fixed |
| MINOR | 3 | All fixed |
| **Total** | **17** | **All fixed** |
