# Changelog — Local LLM Integration

## Overview
Converted the Slack bot from Google Gemini API to a local Qwen3-8B model running via llama.cpp server.

---

## LLM Service (`services/llm_service.py`)

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
handlers/events.py (strips mention tag, dedup guard)
       ▼
graph/workflow.py (LangGraph StateGraph)
       ▼
graph/nodes.py (classify_intent — 12 routes)
       ▼
┌─────────────────────────────────────┐
│ greeting? → build_greeting_response │
│ help?     → build_help_response     │
│ test_llm? → test_llm_connection     │
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

### LLM Connection
`/sab test`

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
