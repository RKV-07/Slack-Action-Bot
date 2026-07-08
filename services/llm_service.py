from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from config import GOOGLE_API_KEY

_llm_instance = None


def _get_llm():
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=GOOGLE_API_KEY,
            temperature=0.3,
        )
    return _llm_instance


def summarize_context(original_message: str, user_input: str) -> str:
    if not GOOGLE_API_KEY:
        return f"Original message: {original_message}"

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
