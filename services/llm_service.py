import requests
import json
import logging
from config import LLAMA_BASE_URL, LLAMA_PARALLEL

logger = logging.getLogger(__name__)

if not LLAMA_PARALLEL:
    logger.warning(
        "LLAMA_PARALLEL is not set. llama-server may default to 1 slot, "
        "causing requests to queue. Set LLAMA_PARALLEL=4 (or your slot count) "
        "in .env to allow concurrent LLM calls."
    )

PERSONA = (
    "You are Slack Actions Bot, a friendly Slack assistant. "
    "Be concise, casual, and helpful. Use occasional emoji. "
    "Keep replies short (1-3 sentences max) unless asked for detail. "
    "You have no ability to follow up later or work in the background — "
    "every reply you give is the ONLY reply the user will get for this "
    "message. Never say 'I'll check', 'let me look into it', 'one moment', "
    "or 'I'll get back to you'. If you don't have enough information to "
    "fully answer, say so directly and tell the user exactly which command "
    "to use instead. "
    "Only these commands exist — never invent alternate syntax or new commands: "
    "`/sab codereview owner/repo#N` (or a PR URL), `/sab latest issues [owner/repo]`, "
    "`/sab latest prs [owner/repo]`, `/sab -r \"task\" @Nm/@Nh` or natural language reminders, "
    "`/sab learn <topic>`, `/sab test`, `/sab summarize`. If asked what's possible, tell the "
    "user to run bare `/sab` for the full list — never make up a new command."
)

# Set to True ONLY if running a reasoning model like DeepSeek-R1 local
# Set to False for standard Llama 3/3.1 models
USE_REASONING_BYPASS = True
_NO_THINK_PREFIX = "/no_think\n"


def _chat_completion(user_msg: str, max_tokens: int = 500, system_msg: str = None) -> str:
    url = f"{LLAMA_BASE_URL}/v1/chat/completions"

    if USE_REASONING_BYPASS:
        user_msg = f"{_NO_THINK_PREFIX}{user_msg}"

    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})

    data = {
        "model": "local",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    try:
        # Local LLM text generation can take a moment; push timeout to 90 seconds
        resp = requests.post(url, json=data, timeout=90)
        if resp.status_code == 200:
            result = resp.json()
            if not result or not isinstance(result, dict) or "choices" not in result:
                print(f"[LLM] Unexpected response body: {str(result)[:200]}")
                return ""
            choices = result.get("choices", [])
            if not choices:
                print("[LLM] Empty choices array")
                return ""
            message = choices[0].get("message", {})
            if not message:
                print("[LLM] Empty message in choices")
                return ""

            content = message.get("content", "")
            reasoning = message.get("reasoning_content", "")

            # Robust fallback logic to extract text cleanly regardless of backend configuration
            final = content if content else reasoning
            return final.strip() if final else ""
        print(f"[LLM] API error: HTTP {resp.status_code}")
        return ""
    except Exception as e:
        print(f"[LLM] Error: {type(e).__name__}: {e}")
        return ""


def generate_reply(user_msg: str) -> str:
    """Generate a persona-consistent reply for casual messages."""
    return _chat_completion(user_msg, max_tokens=150, system_msg=PERSONA)


def summarize_context(original_message: str, user_input: str) -> str:
    """Summarize an action item from thread context."""
    prompt = (
        f"Summarize this action item concisely:\n\n"
        f"Original message: {original_message}\n"
        f"User note: {user_input}\n\n"
        f"What needs to be done?"
    )
    result = _chat_completion(prompt, max_tokens=150, system_msg=PERSONA)
    return result if result else f"Original message: {original_message}"


def summarize_thread_messages(messages: list[dict], max_messages: int = 10) -> str:
    """Summarize a Slack thread conversation."""
    if not messages:
        return "No messages to summarize yet — no real (non-bot) messages were found."

    limited = messages[-max_messages:]

    if len(limited) < 3:
        user_msgs = [m for m in limited if m.get("text", "").strip()]
        if len(user_msgs) < 3:
            preview = "\n".join(f"- {m.get('text', '')}" for m in user_msgs)
            return (
                f"Only {len(user_msgs)} message(s) found — not enough for a meaningful summary.\n\n"
                f"Messages found:\n{preview}"
            )

    thread_text = "\n".join([
        f"User {m.get('user', 'unknown')}: {m.get('text', '')}"
        for m in limited
    ])

    prompt = (
        f"Summarize ONLY the conversation below. Do not invent messages, users, "
        f"or events that are not explicitly present. If the content is too sparse "
        f"to summarize meaningfully, say so plainly instead of guessing.\n\n"
        f"{thread_text}\n\n"
        f"Key points, decisions, and action items?"
    )
    result = _chat_completion(prompt, max_tokens=200, system_msg=PERSONA)
    return result if result else "\n".join([f"- {m.get('text', '')}" for m in limited])
