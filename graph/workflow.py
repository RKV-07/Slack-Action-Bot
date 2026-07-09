from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from .state import BotState
from .nodes import (
    classify_intent,
    extract_github_refs,
    fetch_github_issues,
    fetch_latest_github_items,
    parse_reminder,
    schedule_reminder_node,
    summarize_action,
    build_context_response,
    build_github_response,
    build_help_response,
    build_greeting_response,
    build_chat_response,
    test_llm_connection,
)


def route_after_classification(state: BotState) -> str:
    cmd = state.get("command_type", "help")
    routes = {
        "reminder": "parse_reminder",
        "github": "extract_github",
        "latest_github": "fetch_latest",
        "context": "summarize",
        "help": "help_response",
        "greeting": "greeting_response",
        "chat": "chat_response",
        "test_llm": "test_llm",
    }
    return routes.get(cmd, "help_response")


def build_graph() -> CompiledStateGraph:
    g = StateGraph(BotState)

    g.add_node("classify", classify_intent)
    g.add_node("extract_github", extract_github_refs)
    g.add_node("fetch_github", fetch_github_issues)
    g.add_node("fetch_latest", fetch_latest_github_items)
    g.add_node("parse_reminder", parse_reminder)
    g.add_node("schedule_reminder", schedule_reminder_node)
    g.add_node("summarize", summarize_action)
    g.add_node("context_response", build_context_response)
    g.add_node("github_response", build_github_response)
    g.add_node("help_response", build_help_response)
    g.add_node("greeting_response", build_greeting_response)
    g.add_node("chat_response", build_chat_response)
    g.add_node("test_llm", test_llm_connection)

    g.set_entry_point("classify")

    g.add_conditional_edges("classify", route_after_classification, {
        "parse_reminder": "parse_reminder",
        "extract_github": "extract_github",
        "fetch_latest": "fetch_latest",
        "summarize": "summarize",
        "help_response": "help_response",
        "greeting_response": "greeting_response",
        "chat_response": "chat_response",
        "test_llm": "test_llm",
    })

    g.add_edge("parse_reminder", "schedule_reminder")
    g.add_edge("schedule_reminder", END)
    g.add_edge("extract_github", "fetch_github")
    g.add_edge("fetch_github", "github_response")
    g.add_edge("github_response", END)
    g.add_edge("fetch_latest", "github_response")
    g.add_edge("summarize", "context_response")
    g.add_edge("context_response", END)
    g.add_edge("help_response", END)
    g.add_edge("greeting_response", END)
    g.add_edge("chat_response", END)
    g.add_edge("test_llm", END)

    return g.compile()


sab_graph = build_graph()
