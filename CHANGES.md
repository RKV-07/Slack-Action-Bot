# Changelog - Local LLM Integration

## Overview
Converted the Slack bot from using Google Gemini API to a local Qwen3-8B model running via llama.cpp server.

---

## 1. LLM Service (`services/llm_service.py`)

### Before
- Used `langchain-google-genai` with Gemini API
- Required `GOOGLE_API_KEY`
- Single `summarize_context()` function

### After
- Uses direct HTTP requests to llama.cpp server (OpenAI-compatible API)
- No API key needed
- Added `/no_think` prefix to disable Qwen3 thinking mode (faster responses)
- Added `reasoning_content` fallback (Qwen3 puts thinking in separate field)
- Added timeout and connection error handling

### Key Functions
```python
_chat_completion(prompt, max_tokens=500, enable_thinking=False)
summarize_context(original_message, user_input)
summarize_thread_messages(messages, max_messages=10)
generate_mention_reply(context, original_message)
```

---

## 2. Config (`config.py`)

### Added
```python
LLAMA_BASE_URL = os.environ.get("LLAMA_BASE_URL", "http://localhost:8080")
```

### Usage
- Default: `http://localhost:8080` (local server)
- Cloudflare tunnel: `https://smtp-knight-wanted-serum.trycloudflare.com`

---

## 3. Graph State (`graph/state.py`)

### Added Command Types
```python
command_type: Literal[
    "context", "reminder", "github", "mention", 
    "unknown", "latest_github", "greeting", "test_llm"
]
```

### Added Fields
```python
thread_messages: list[dict]  # Messages from Slack thread
max_messages: int             # Max messages to summarize
```

---

## 4. Graph Nodes (`graph/nodes.py`)

### New Functions

#### `build_greeting_response()`
- Handles casual messages like "hi", "hey", "hello"
- Uses quick reply dictionary for instant responses
- Falls back to LLM for unknown greetings
- Triggered by patterns: `hi`, `hey`, `hello`, `heu`, `hlo`, `hlw`, `how are u`, `what can you do`, etc.

#### `test_llm_connection()`
- Tests if llama server is running
- Triggered by: `test llm` or `test`
- Returns connection status

#### Updated `classify_intent()`
- Checks greeting patterns BEFORE ActionContext
- Strips `@Slack Actions Bot` mentions before matching
- Routes to `greeting` or `test_llm` command types

### Quick Reply Dictionary
```python
quick_replies = {
    "hi": "Hey there! 👋 I'm Slack Actions Bot...",
    "hey": "Hey! 👋 What's up?...",
    "hello": "Hello! 👋 I'm your Slack Actions Bot...",
    "how are u": "I'm doing great! 😊...",
    "what can you do": "I can help with:...",
    # ... more greetings
}
```

---

## 5. Graph Workflow (`graph/workflow.py`)

### Added Nodes
- `greeting_response` -> `build_greeting_response`
- `test_llm` -> `test_llm_connection`

### Added Routing
```python
if cmd == "greeting":
    return "greeting_response"
if cmd == "test_llm":
    return "test_llm"
```

---

## 6. Event Handlers (`handlers/events.py`)

### Fixed Mention Parsing
```python
# Before: raw_input = original_msg  (contains <@BOT_ID> tag)
# After:
clean_msg = re.sub(r'<@[A-Z0-9]+>', '', original_msg).strip()
raw_input = clean_msg if clean_msg else original_msg
```

### Why
When user sends `@Slack Actions Bot hey`, Slack stores it as `<@U123456> hey`. The bot now strips the mention tag before processing.

---

## 7. Dependencies (`pyproject.toml`)

### Removed
- `langchain-google-genai>=2.0.0`

### Kept
- `langchain-core>=0.3.0` (for state management)
- `requests>=2.31.0` (for HTTP calls to llama server)

---

## 8. Environment Variables (`.env`)

### Added
```bash
LLAMA_BASE_URL=http://localhost:8080
# OR for Cloudflare tunnel:
LLAMA_BASE_URL=https://smtp-knight-wanted-serum.trycloudflare.com
```

### Removed (no longer needed)
```bash
# GOOGLE_API_KEY=...  (not needed for local LLM)
```

---

## How to Test

### Test LLM Connection
In Slack: `@Slack Actions Bot test llm`

### Test Greetings
In Slack, mention the bot:
- `@Slack Actions Bot hey`
- `@Slack Actions Bot hello`
- `@Slack Actions Bot how are you`
- `@Slack Actions Bot what can you do`

### Test Reminders
`/sab -r "Check PR" @30m`

### Test Summarization
Mention bot in a thread with messages

### Test GitHub
Mention `owner/repo#123` or `/sab latest issues`

---

## Architecture

```
User mentions bot
       ↓
handlers/events.py (strips mention tag)
       ↓
graph/workflow.py (LangGraph)
       ↓
graph/nodes.py (classify_intent)
       ↓
┌─────────────────────────────────────┐
│ greeting? → build_greeting_response │
│ test_llm? → test_llm_connection     │
│ reminder? → parse_reminder          │
│ github?   → extract_github          │
│ context?  → summarize_action        │
│ unknown?  → build_unknown_response  │
└─────────────────────────────────────┘
       ↓
services/llm_service.py (_chat_completion)
       ↓
llama-server (Qwen3-8B) /no_think
       ↓
Response to Slack
```
