import requests
import json
from config import LLAMA_BASE_URL


def _chat_completion(prompt: str, max_tokens: int = 500, enable_thinking: bool = False) -> str:
    url = f"{LLAMA_BASE_URL}/v1/chat/completions"
    
    if not enable_thinking:
        prompt = f"/no_think\n{prompt}"
    
    data = {
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    try:
        response = requests.post(url, json=data, timeout=60)
        if response.status_code == 200:
            try:
                result = response.json()
                message = result["choices"][0]["message"]
                content = message.get("content", "")
                reasoning = message.get("reasoning_content", "")
                final_content = content or reasoning
                return final_content.strip() if final_content else ""
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                print(f"LLM parse error: {e}")
                return ""
        else:
            print(f"LLM API error: {response.status_code}")
            return ""
    except requests.exceptions.Timeout:
        print("LLM API timeout")
        return ""
    except requests.exceptions.ConnectionError:
        print("LLM API connection error - is the server running?")
        return ""
    except Exception as e:
        print(f"LLM error: {e}")
        return ""


def summarize_context(original_message: str, user_input: str) -> str:
    prompt = (
        f"Summarize this action item concisely:\n\n"
        f"Original message: {original_message}\n"
        f"User note: {user_input}\n\n"
        f"Provide a 1-2 sentence summary of what needs to be done."
    )
    result = _chat_completion(prompt)
    return result if result else f"Original message: {original_message}"


def summarize_thread_messages(messages: list[dict], max_messages: int = 10) -> str:
    if not messages:
        return "No messages to summarize."

    limited_messages = messages[:max_messages]
    thread_text = "\n".join([
        f"User {m.get('user', 'unknown')}: {m.get('text', '')}"
        for m in limited_messages
    ])

    prompt = (
        f"Summarize this Slack conversation concisely:\n\n"
        f"{thread_text}\n\n"
        f"Provide a clear summary of the key points, decisions, and action items."
    )
    result = _chat_completion(prompt)
    return result if result else "\n".join([f"- {m.get('text', '')}" for m in limited_messages])


def generate_mention_reply(context: str, original_message: str) -> str:
    prompt = (
        f"You are a helpful Slack bot. Generate a concise, friendly reply to a mention.\n\n"
        f"Context: {context}\n"
        f"Original message: {original_message}\n\n"
        f"Generate a brief, helpful response."
    )
    result = _chat_completion(prompt)
    return result if result else "Hey! You were mentioned. Use `/sab` to handle this."
