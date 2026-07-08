from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from config import LLAMA_BASE_URL

_llm_instance = None


def _get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = ChatOpenAI(
            base_url=f"{LLAMA_BASE_URL}/v1",
            api_key="not-needed",
            model="local",
            temperature=0.3,
        )
    return _llm_instance


def summarize_context(original_message: str, user_input: str) -> str:
    llm = _get_llm()
    prompt = (
        f"Summarize this action item concisely:\n\n"
        f"Original message: {original_message}\n"
        f"User note: {user_input}\n\n"
        f"Provide a 1-2 sentence summary of what needs to be done."
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as e:
        print(f"LLM error: {e}")
        return f"Original message: {original_message}"


def summarize_thread_messages(messages: list[dict], max_messages: int = 10) -> str:
    if not messages:
        return "No messages to summarize."

    limited_messages = messages[:max_messages]
    thread_text = "\n".join([
        f"User {m.get('user', 'unknown')}: {m.get('text', '')}"
        for m in limited_messages
    ])

    llm = _get_llm()
    prompt = (
        f"Summarize this Slack conversation concisely:\n\n"
        f"{thread_text}\n\n"
        f"Provide a clear summary of the key points, decisions, and action items."
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as e:
        print(f"LLM error: {e}")
        return "\n".join([f"- {m.get('text', '')}" for m in limited_messages])


def generate_mention_reply(context: str, original_message: str) -> str:
    llm = _get_llm()
    prompt = (
        f"You are a helpful Slack bot. Generate a concise, friendly reply to a mention.\n\n"
        f"Context: {context}\n"
        f"Original message: {original_message}\n\n"
        f"Generate a brief, helpful response."
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as e:
        print(f"LLM error: {e}")
        return "Hey! You were mentioned. Use `/sab` to handle this."
