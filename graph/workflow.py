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
    build_mention_response,
    build_unknown_response,
    build_greeting_response,
    test_llm_connection,
)


def route_after_classification(state: BotState) -> str:
    cmd = state.get("command_type", "unknown")
    if cmd == "reminder":
        return "parse_reminder"
    if cmd == "github":
        return "extract_github"
    if cmd == "latest_github":
        return "fetch_latest"
    if cmd == "context":
        return "summarize"
    if cmd == "mention":
        return "mention_response"
    if cmd == "greeting":
        return "greeting_response"
    if cmd == "test_llm":
        return "test_llm"
    return "unknown_response"


def build_graph() -> CompiledStateGraph:
    workflow = StateGraph(BotState)

    workflow.add_node("classify", classify_intent)
    workflow.add_node("extract_github", extract_github_refs)
    workflow.add_node("fetch_github", fetch_github_issues)
    workflow.add_node("fetch_latest", fetch_latest_github_items)
    workflow.add_node("parse_reminder", parse_reminder)
    workflow.add_node("schedule_reminder", schedule_reminder_node)
    workflow.add_node("summarize", summarize_action)
    workflow.add_node("context_response", build_context_response)
    workflow.add_node("github_response", build_github_response)
    workflow.add_node("mention_response", build_mention_response)
    workflow.add_node("unknown_response", build_unknown_response)
    workflow.add_node("greeting_response", build_greeting_response)
    workflow.add_node("test_llm", test_llm_connection)

    workflow.set_entry_point("classify")

    workflow.add_conditional_edges(
        "classify",
        route_after_classification,
        {
            "parse_reminder": "parse_reminder",
            "extract_github": "extract_github",
            "fetch_latest": "fetch_latest",
            "summarize": "summarize",
            "mention_response": "mention_response",
            "unknown_response": "unknown_response",
            "greeting_response": "greeting_response",
            "test_llm": "test_llm",
        },
    )

    workflow.add_edge("parse_reminder", "schedule_reminder")
    workflow.add_edge("schedule_reminder", END)

    workflow.add_edge("extract_github", "fetch_github")
    workflow.add_edge("fetch_github", "github_response")
    workflow.add_edge("github_response", END)

    workflow.add_edge("fetch_latest", "github_response")

    workflow.add_edge("summarize", "context_response")
    workflow.add_edge("context_response", END)

    workflow.add_edge("mention_response", END)
    workflow.add_edge("unknown_response", END)
    workflow.add_edge("greeting_response", END)
    workflow.add_edge("test_llm", END)

    return workflow.compile()


sab_graph = build_graph()
