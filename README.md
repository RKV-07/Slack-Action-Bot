# Slack Advanced Actions Bot (SAB)

A smart Slack bot that contextualizes mentions, sets reminders, and auto-detects GitHub issues/PRs — all powered by **LangGraph** for agentic workflow orchestration.

## Features

- **Action Context** — `/sab` in a thread captures who mentioned you and what they asked
- **Smart Reminders** — `/sab -r "Check the bug" @30m` sets timed reminders via APScheduler
- **GitHub Lookup** — Mention `#123` or `org/repo#456` and the bot auto-fetches issue status
- **Mention Detection** — Bot suggests `/sab` when you're mentioned in a channel

## Architecture

Built with **LangGraph StateGraph** for deterministic, debuggable agentic workflows:

```
User Input
    |
    v
[classify_intent] --- conditional routing ---> parse_reminder --> schedule_reminder
    |                                             |
    +---> extract_github_refs --> fetch_github --> github_response
    |
    +---> summarize_action --> context_response
    |
    +---> mention_response / unknown_response
```

### Tech Stack
- **LangGraph** — StateGraph workflow orchestration
- **Slack Bolt** — Socket Mode event handling
- **Google Gemini** — LLM for context summarization
- **APScheduler** — Background reminder scheduling
- **GitHub API** — Issue/PR live status
- **Pydantic** — Type-safe state models

## Project Structure

```
Slack-Action-Bot/
├── main.py              # Entry point, Slack Bolt app setup
├── config.py            # Environment variable validation
├── graph/
│   ├── state.py         # BotState TypedDict + Pydantic models
│   ├── nodes.py         # All workflow node functions
│   └── workflow.py      # LangGraph StateGraph definition
├── handlers/
│   ├── commands.py      # /sab slash command handler
│   └── events.py        # Message + app_mention event handlers
├── services/
│   ├── github_service.py    # GitHub API integration
│   ├── llm_service.py       # Gemini LLM summarization
│   └── reminder_service.py  # APScheduler reminder scheduling
├── .env.example
├── pyproject.toml
└── CHANGELOG.md
```

## Setup

1. Copy `.env.example` to `.env` and fill in your tokens:
   ```
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_APP_TOKEN=xapp-...
   SLACK_SIGNING_SECRET=...
   GITHUB_TOKEN=ghp-...
   DEFAULT_GITHUB_REPO=owner/repo
   GOOGLE_API_KEY=...
   ```

2. Install dependencies:
   ```
   uv sync
   ```

3. Run the bot:
   ```
   uv run main.py
   ```

## Commands

| Command | Description |
|---------|-------------|
| `/sab` | Capture action context in a thread |
| `/sab -r "task" @30m` | Set a reminder in 30 minutes |
| `/sab -r "task" @2h` | Set a reminder in 2 hours |
| `#123` | Auto-fetch GitHub issue #123 |
| `org/repo#456` | Auto-fetch issue from specific repo |
