# Slack Action Bot — Architecture & Design

## Overview

A Slack bot that uses **LangGraph** for agentic workflow orchestration, **local Qwen3-8B** for LLM inference, and **MCP** for extensible tool access (GitHub, Fetch, custom Slack server).

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Slack Workspace                              │
│  User sends message or /sab command                                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Socket Mode (WebSocket)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main.py (Bolt App)                                                 │
│  ├── /sab command ──► cmd_sab() ──► handle_sab_command()           │
│  ├── app_mention ──► on_mention() ──► handle_app_mention()         │
│  ├── message ──► on_message() ──► handle_message_event()           │
│  ├── [trigger_id dedup guard on /sab]                                  │
│  ├── [event_ts dedup guard on mention/message]                         │
│  ├── [processing reaction decorator]                                   │
│  └── [MCP init in background daemon thread]                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  handlers/shared.py                                                 │
│  ├── is_real_message() ── filters bot msgs, subtypes, empty        │
│  ├── fetch_thread_messages() ── Slack API (conversations_replies)   │
│  ├── fetch_channel_messages() ── conversations_history + .reverse() │
│  ├── build_initial_state() ── constructs BotState TypedDict        │
│  └── _get_bot_user_id() ── cached after first call                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  graph/workflow.py (LangGraph StateGraph)                           │
│                                                                      │
│  ┌──────────┐                                                       │
│  │ classify │ ◄── entry_point (12 conditional routes)               │
│  └────┬─────┘                                                       │
│       ├─────────────────────────────────────────────────────────┐   │
│       │         │          │          │          │               │   │
│       ▼         ▼          ▼          ▼          ▼               │   │
│  ┌─────────┐┌────────┐┌─────────┐┌────────┐┌─────────┐         │   │
│  │reminder ││github  ││context  ││help    ││chat     │         │   │
│  │parse    ││extract ││summarize││static  ││LLM      │         │   │
│  │schedule ││fetch   ││channel  │└────────┘└─────────┘         │   │
│  │list     ││response││response │                               │   │
│  │cancel   │└────────┘└─────────┘                               │   │
│  └─────────┘                                                     │   │
│       │     ┌──────────────────────────────┐                     │   │
│       │     │ learn_research                │                     │   │
│       │     │ learn_structure ──► response  │                     │   │
│       │     │ learn_resources               │                     │   │
│       │     └──────────────────────────────┘                     │   │
│       │     ┌──────────────────────────────┐                     │   │
│       │     │ codereview_fetch              │                     │   │
│       │     │ ┌──────┬──────┬──────────┐   │                     │   │
│       │     │ │secure│perform│best_prac │   │──► merge ──► resp  │   │
│       │     │ └──────┴──────┴──────────┘   │   (fan-out)        │   │
│       │     └──────────────────────────────┘                     │   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐
│ services/        │ │ services/    │ │ services/        │
│ llm_service.py   │ │ github_svc   │ │ mcp_client.py    │
│                  │ │              │ │                  │
│ _chat_completion │ │ fetch_*()    │ │ AsyncExitStack   │
│ summarize_msgs   │ │ rate_limit   │ │ background loop  │
│ PERSONA          │ │ TTL cache    │ │ call_tool()      │
│ /no_think prefix │ │ _headers()   │ │ _evict_session() │
└────────┬─────────┘ └──────┬───────┘ └────────┬─────────┘
         ▼                  ▼                   ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐
│ llama-server     │ │ GitHub API   │ │ MCP Servers      │
│ Qwen3-8B         │ │ REST         │ │ ├── @mcp/github  │
│ localhost:8080   │ │              │ │ ├── mcp-fetch    │
│ --parallel 4     │ │              │ │ └── mcp-slack    │
└──────────────────┘ └──────────────┘ └──────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────┐
│ codereview_svc   │ │ learn_svc    │ │ reminder_svc     │
│                  │ │              │ │                  │
│ parse_review_ref │ │ research()   │ │ schedule_remind  │
│ _run_semgrep()   │ │ structure()  │ │ list_reminders   │
│ 3 reviewers      │ │ curate()     │ │ cancel_reminder  │
│ merge_reviews    │ │ _tavily()    │ │ SQLite jobstore  │
│ fan-out pattern  │ │ GitHub+Web   │ │ reminders.db     │
└──────────────────┘ └──────────────┘ └──────────────────┘
```

## Key Design Decisions

| Decision | Why |
|---|---|
| LangGraph StateGraph | Structured routing, fan-out for parallel reviewers |
| Local Qwen3-8B | Zero API cost, fast inference, no rate limits |
| `/no_think` prefix | Qwen3 returns reasoning in `reasoning_content` field; prefix bypasses |
| MCP primary, direct API fallback | Extensible tool access, graceful degradation |
| `difflib` fuzzy matching | Typo tolerance without new dependencies |
| SQLite jobstore | Reminders survive bot restarts |
| `cachetools.TTLCache` | 2-min cache prevents redundant GitHub API calls |
| Semgrep in security reviewer | Real static analysis grounded in actual code findings |
| PR risk score | One-line risk indicator (🔴/🟡/🟢) from Semgrep + LLM |
| Tavily in learn service | Real URLs instead of LLM-invented links |
| MCP source-transparency footer | Visible proof of MCP usage in every review/resource output |
| `_call_with_backoff()` | Rate-limit resilience for Slack API calls |
| `md_to_slack_mrkdwn()` | Fixes broken Markdown before posting to Slack |
| `trigger_id` dedup on `/sab` | Prevents Socket Mode redelivery duplicates |
| `event_ts` dedup on mention/message | Prevents duplicate processing on redelivered events |
| `is_real_message()` unified filter | Single source of truth across all 3 fetch paths |
| `ThreadPoolExecutor(5)` | Bounded concurrent graph executions |

## BotState TypedDict

```python
class BotState(TypedDict):
    command_type: Literal[
        "context", "reminder", "github", "mention",
        "latest_github", "greeting", "test_llm", "help", "chat",
        "learn", "codereview", "reminder_list", "reminder_cancel",
    ]
    action_context: Optional[ActionContext]
    reminder_data: Optional[ReminderData]
    github_refs: list[str]
    github_results: list[dict]
    user_id: str
    channel_id: str
    message_ts: str
    raw_input: str
    response_message: str
    needs_llm: bool
    llm_summary: Optional[str]
    thread_messages: list[dict]
    max_messages: int
    learn_topic: str
    learn_resources: list[dict]
    learn_path: dict
    review_pr_data: dict
    review_security: str
    review_performance: str
    review_best_practices: str
```

## Intent Classification Flow

```
classify_intent(state):
  empty input ──────────────────────► help (or context if thread msgs)
  "test" / "test llm" ─────────────► test_llm
  "learn ..." ─────────────────────► learn (via alias or regex)
  "codereview ..." ────────────────► codereview (via alias or regex)
  "coderview" / "review" / "pr" ──► codereview (difflib fuzzy match)
  "summarize" / "catch me up" ────► context
  "-r" / "remind" ────────────────► reminder
  "reminders" / "reminder cancel" ► reminder_list / reminder_cancel
  "latest issues/prs" ────────────► latest_github
  "what can you do" / "help" ─────► help
  "hi" / "hey" / "hello" ────────► greeting
  github.com/.../pull/N ──────────► codereview
  github.com/.../issues/N ────────► github
  owner/repo#123 ─────────────────► github
  thread messages exist ──────────► context
  default ────────────────────────► chat
```

## MCP Server Configuration

| Server | Package | Transport | Purpose |
|---|---|---|---|
| GitHub | `@modelcontextprotocol/server-github` | stdio (npm) | PR/issue fetch, repo search |
| Fetch | `mcp-server-fetch` | stdio (uvx) | Web content fetching |
| Slack | `services/mcp_slack_server.py` | stdio (in-repo) | Channel/thread message fetch |

All MCP servers initialize in a background daemon thread at startup. The bot boots immediately and connects MCP asynchronously.

## Dependencies

| Package | Purpose |
|---|---|
| `langgraph` | StateGraph workflow orchestration |
| `slack-bolt` | Socket Mode event handling |
| `requests` | HTTP calls to llama-server and GitHub API |
| `apscheduler[sqlalchemy]` | SQLite-persisted reminder scheduling |
| `pydantic` | Type-safe state models |
| `mcp` | MCP Python SDK client (GitHub, Fetch, custom Slack) |
| `anyio` | Async runtime for MCP |
| `cachetools` | TTL cache for GitHub repos |
| `dateparser` | Natural language time parsing |
| `python-dotenv` | Environment variable loading |
