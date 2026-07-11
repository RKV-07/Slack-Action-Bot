# Slack Advanced Actions Bot (SAB)

A smart Slack bot powered by **LangGraph** and **local Qwen3-8B** for agentic workflow orchestration — no cloud API costs.

## Features

| Feature | Command | Description |
|---|---|---|
| Summarize | `/sab summarize` or mention | Summarizes last 25 messages using local LLM |
| Reminders | `/sab -r "task" @30m` | Set timed reminders (persisted in SQLite) |
| Natural Language Reminders | `/sab remind me to...` | dateparser handles "tomorrow at 3pm" |
| List Reminders | `/sab reminders` | Show all pending reminders with IDs |
| Cancel Reminder | `/sab reminder cancel <id>` | Cancel by job ID |
| GitHub Issue/PR Lookup | `owner/repo#123` or paste URL | Fetches issue/PR details |
| Latest Issues | `/sab latest issues` | Newest open issues across all repos |
| Latest PRs | `/sab latest prs` | Newest open PRs across all repos |
| Code Review | `/sab codereview owner/repo#123` | 3-subagent review (Security + Performance + Best Practices) |
| Semgrep Security | (auto in code review) | Real static analysis grounding |
| Learning Paths | `/sab learn <topic>` | 3-agent research → structure → resources |
| Web Search | (auto in /learn) | Tavily API for real URLs |
| Help | `/sab` or "what can you do" | Static command list |
| LLM Test | `/sab test` | Verifies llama-server connection |
| Typo Tolerance | "coderview", "review", "pr" | difflib fuzzy matching |

## Architecture

Built with **LangGraph StateGraph** for deterministic, debuggable agentic workflows:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Slack Workspace                              │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Socket Mode (WebSocket)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main.py (Bolt App)                                                 │
│  ├── /sab command ──► cmd_sab() ──► handle_sab_command()           │
│  ├── app_mention ──► on_mention() ──► handle_app_mention()         │
│  └── message ──► on_message() ──► handle_message_event()           │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  graph/workflow.py (LangGraph StateGraph)                           │
│  ┌──────────┐                                                       │
│  │ classify │ ◄── entry_point                                       │
│  └────┬─────┘                                                       │
│       │ 12 conditional routes                                       │
│       ├──► reminder (parse → schedule / list / cancel)              │
│       ├──► github (extract → fetch → response)                      │
│       ├──► context (summarize → response)                           │
│       ├──► learn (research → structure → resources → response)      │
│       ├──► codereview (fetch → [security,performance,best] → merge) │
│       ├──► help / greeting / chat / test_llm                        │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  services/                                                          │
│  ├── llm_service.py ──► llama-server (Qwen3-8B, localhost:8080)    │
│  ├── github_service.py ──► GitHub API (TTL cache, rate-limit track) │
│  ├── codereview_service.py ──► Semgrep + 3 LLM subagents           │
│  ├── learn_service.py ──► Tavily search + GitHub repos + LLM        │
│  ├── reminder_service.py ──► SQLite-backed APScheduler              │
│  └── mcp_client.py ──► GitHub/Fetch/Slack MCP servers               │
└─────────────────────────────────────────────────────────────────────┘
```

### Tech Stack
- **LangGraph** — StateGraph workflow orchestration with fan-out/fan-in
- **Slack Bolt** — Socket Mode event handling
- **Local Qwen3-8B** — LLM via llama-server (no cloud API)
- **APScheduler** — SQLite-persisted reminder scheduling
- **GitHub API** — Issue/PR lookup with TTL cache
- **MCP** — Model Context Protocol for extensible tool access
- **Semgrep** — Real static analysis for security reviews
- **Tavily** — Web search for verified learning resources
- **dateparser** — Natural language time parsing
- **difflib** — Typo-tolerant command matching
- **Pydantic** — Type-safe state models

## Project Structure

```
Slack-Action-Bot/
├── main.py                      # Bolt app, MCP init, dedup guard
├── config.py                    # Env vars (tokens, endpoints)
├── graph/
│   ├── state.py                 # BotState TypedDict, ReminderData
│   ├── nodes.py                 # 30+ node functions
│   └── workflow.py              # StateGraph build, routing logic
├── handlers/
│   ├── commands.py              # /sab slash command handler
│   ├── events.py                # app_mention + message handlers
│   └── shared.py                # is_real_message, fetch_*, build_initial_state
├── services/
│   ├── llm_service.py           # Local LLM calls, PERSONA, summarize
│   ├── github_service.py        # GitHub API, TTL cache, rate-limit tracking
│   ├── codereview_service.py    # 3-subagent review, Semgrep
│   ├── learn_service.py         # 3-agent learning path, Tavily search
│   ├── reminder_service.py      # SQLite-backed APScheduler
│   ├── mcp_client.py            # MCP AsyncExitStack, background loop
│   ├── mcp_slack_server.py      # Custom Slack MCP server (stdio)
│   ├── slack_summarize_service.py # MCP-first channel summary
│   └── slack_features.py        # Processing reaction decorator
├── reminders.db                 # SQLite persistent reminders
├── test_all.py                  # 131 unit tests
├── test_e2e.py                  # 45 end-to-end tests
└── pyproject.toml               # Dependencies (uv-managed)
```

## Setup

1. Start llama-server with Qwen3-8B:
   ```bash
   llama-server -m models/qwen3-8b-q4_k_m.gguf --port 8080 --parallel 4
   ```

2. Copy `.env.example` to `.env` and fill in:
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   SLACK_SIGNING_SECRET=...
   GITHUB_TOKEN=ghp-...
   LLAMA_BASE_URL=http://localhost:8080
   LLAMA_PARALLEL=4
   TAVILY_API_KEY=tvly-...        # optional, for /learn web search
   ```

3. Install dependencies:
   ```bash
   uv sync
   ```

4. Run the bot:
   ```bash
   uv run main.py
   ```

## Commands

| Command | Description |
|---------|-------------|
| `/sab` | Show help / command list |
| `/sab summarize` | Summarize channel or thread messages |
| `/sab -r "task" @30m` | Set a reminder in 30 minutes |
| `/sab remind me to...` | Natural language reminder |
| `/sab reminders` | List pending reminders |
| `/sab reminder cancel <id>` | Cancel a reminder |
| `/sab latest issues` | Newest open issues across all repos |
| `/sab latest prs` | Newest open PRs across all repos |
| `/sab codereview owner/repo#123` | 3-perspective code review |
| `/sab learn <topic>` | Structured learning path |
| `/sab test` | Test LLM connection |
| `owner/repo#123` | Auto-fetch issue/PR details |
| Paste GitHub URL | Auto-fetch issue/PR details |
