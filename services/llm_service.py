import time
import requests
import logging
from config import (
    LLAMA_BASE_URL, LLAMA_PARALLEL, LLM_PROVIDER, LLM_FALLBACK_ENABLED,
    GOOGLE_API_KEY, GEMINI_MODEL, REMOTE_LLM_BASE_URL, REMOTE_LLM_MODEL,
)

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

USE_REASONING_BYPASS = True
_NO_THINK_PREFIX = "/no_think\n"


def _local_completion(user_msg: str, max_tokens: int = 500, system_msg: str = None) -> str:
    """Call local Qwen3 via llama-server (primary default)."""
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
        resp = requests.post(url, json=data, timeout=90)
        # Retry once on 503 (model still loading at boot)
        if resp.status_code == 503:
            print("[LLM] 503 — model still loading, retrying in 3s...")
            time.sleep(3)
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
            final = content if content else reasoning
            return final.strip() if final else ""
        print(f"[LLM] Local API error: HTTP {resp.status_code} - {resp.text[:300]}")
        return ""
    except Exception as e:
        print(f"[LLM] Local error: {type(e).__name__}: {e}")
        return ""


def _gemini_completion(user_msg: str, max_tokens: int = 500, system_msg: str = None) -> str:
    """Call Google Gemini API (fallback when local fails)."""
    if not GOOGLE_API_KEY:
        return ""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    parts = []
    if system_msg:
        parts.append({"text": f"{system_msg}\n\n{user_msg}"})
    else:
        parts.append({"text": user_msg})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    try:
        resp = requests.post(
            url,
            params={"key": GOOGLE_API_KEY},
            json=payload,
            timeout=90,
        )
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
        print(f"[LLM] Gemini error: {type(e).__name__}: {e}")
        return ""


def _remote_completion(user_msg: str, max_tokens: int = 500, system_msg: str = None) -> str:
    """Call remote OpenAI-compatible endpoint (qwen3.5-397b / glm-5.2)."""
    if not REMOTE_LLM_BASE_URL:
        return ""

    messages = []
    if system_msg:
        messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": user_msg})

    data = {
        "model": REMOTE_LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    try:
        resp = requests.post(
            f"{REMOTE_LLM_BASE_URL}/v1/chat/completions",
            json=data,
            timeout=90,
        )
        if resp.status_code == 200:
            result = resp.json()
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                return content.strip() if content else ""
        print(f"[LLM] Remote API error: HTTP {resp.status_code} - {resp.text[:300]}")
        return ""
    except Exception as e:
        print(f"[LLM] Remote error: {type(e).__name__}: {e}")
        return ""


def _chat_completion(user_msg: str, max_tokens: int = 500, system_msg: str = None) -> str:
    """Dispatch to primary provider with fallback chain: local → remote (glm-5.2) → gemini."""
    _providers = {
        "local": _local_completion,
        "remote": _remote_completion,
        "gemini": _gemini_completion,
    }

    primary = LLM_PROVIDER if LLM_PROVIDER in _providers else "local"
    primary_fn = _providers[primary]

    result = primary_fn(user_msg, max_tokens, system_msg)
    if result:
        return result

    if not LLM_FALLBACK_ENABLED:
        return ""

    # Fallback chain: try remaining providers
    fallback_order = {
        "local": ["remote", "gemini"],
        "remote": ["local", "gemini"],
        "gemini": ["local", "remote"],
    }
    for fallback in fallback_order.get(primary, ["remote", "gemini"]):
        if fallback == "gemini" and not GOOGLE_API_KEY:
            continue
        if fallback == "remote" and not REMOTE_LLM_BASE_URL:
            continue
        print(f"[LLM] Primary {primary} failed, falling back to {fallback}")
        result = _providers[fallback](user_msg, max_tokens, system_msg)
        if result:
            return result

    return ""


def check_local_llm() -> bool:
    return bool(_local_completion("Say OK", max_tokens=5))


def check_remote_llm() -> bool:
    return bool(_remote_completion("Say OK", max_tokens=5)) if REMOTE_LLM_BASE_URL else False


def check_llm_context_size(min_expected: int = 16384):
    """Check llama-server context size at boot. Warns if too small for codereview/learn."""
    try:
        resp = requests.get(f"{LLAMA_BASE_URL}/props", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            n_ctx = (
                data.get("n_ctx")
                or data.get("default_generation_settings", {}).get("n_ctx")
            )
            if n_ctx and n_ctx < min_expected:
                print(
                    f"[LLM] WARNING: context is {n_ctx} tokens, expected ≥{min_expected}. "
                    f"Restart llama-server with: llama-server -m <model> --port 8080 -c 16384"
                )
            elif n_ctx:
                print(f"[LLM] Context size: {n_ctx} tokens (OK)")
    except Exception as e:
        print(f"[LLM] Could not verify context size: {e}")


def check_gemini_llm() -> bool:
    return bool(_gemini_completion("Say OK", max_tokens=5)) if GOOGLE_API_KEY else False


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
