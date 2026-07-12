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
    reminder_list_node,
    reminder_cancel_node,
    summarize_action,
    build_context_response,
    build_github_response,
    build_help_response,
    build_greeting_response,
    build_chat_response,
    test_llm_connection,
    learn_research,
    learn_structure,
    learn_resources,
    learn_response,
    codereview_fetch,
    codereview_security,
    codereview_performance,
    codereview_best_practices,
    codereview_merge,
    codereview_response,
    digest_node,
    duplicate_check_node,
    release_notes_node,
    search_node,
)


def route_after_classification(state: BotState) -> str:
    cmd = state.get("command_type", "help")
    routes = {
        "reminder": "parse_reminder",
        "reminder_list": "reminder_list",
        "reminder_cancel": "reminder_cancel",
        "github": "extract_github",
        "latest_github": "fetch_latest",
        "context": "summarize",
        "help": "help_response",
        "greeting": "greeting_response",
        "chat": "chat_response",
        "test_llm": "test_llm",
        "learn": "learn_research",
        "codereview": "codereview_fetch",
        "digest": "digest",
        "duplicate": "duplicate_check",
        "release_notes": "release_notes",
        "search": "search",
    }
    return routes.get(cmd, "help_response")


def route_codereview(state: BotState) -> list[str]:
    """If fetch already set an error response, skip the subagents."""
    if state.get("response_message"):
        return ["codereview_response"]
    return ["codereview_security", "codereview_performance", "codereview_best_practices"]


def build_graph() -> CompiledStateGraph:
    g = StateGraph(BotState)

    g.add_node("classify", classify_intent)
    g.add_node("extract_github", extract_github_refs)
    g.add_node("fetch_github", fetch_github_issues)
    g.add_node("fetch_latest", fetch_latest_github_items)
    g.add_node("parse_reminder", parse_reminder)
    g.add_node("schedule_reminder", schedule_reminder_node)
    g.add_node("reminder_list", reminder_list_node)
    g.add_node("reminder_cancel", reminder_cancel_node)
    g.add_node("summarize", summarize_action)
    g.add_node("context_response", build_context_response)
    g.add_node("github_response", build_github_response)
    g.add_node("help_response", build_help_response)
    g.add_node("greeting_response", build_greeting_response)
    g.add_node("chat_response", build_chat_response)
    g.add_node("test_llm", test_llm_connection)

    # Learn nodes
    g.add_node("learn_research", learn_research)
    g.add_node("learn_structure", learn_structure)
    g.add_node("learn_resources", learn_resources)
    g.add_node("learn_response", learn_response)

    # Code review nodes
    g.add_node("codereview_fetch", codereview_fetch)
    g.add_node("codereview_security", codereview_security)
    g.add_node("codereview_performance", codereview_performance)
    g.add_node("codereview_best_practices", codereview_best_practices)
    g.add_node("codereview_merge", codereview_merge)
    g.add_node("codereview_response", codereview_response)

    # New feature nodes
    g.add_node("digest", digest_node)
    g.add_node("duplicate_check", duplicate_check_node)
    g.add_node("release_notes", release_notes_node)
    g.add_node("search", search_node)

    g.set_entry_point("classify")

    g.add_conditional_edges("classify", route_after_classification, {
        "parse_reminder": "parse_reminder",
        "reminder_list": "reminder_list",
        "reminder_cancel": "reminder_cancel",
        "extract_github": "extract_github",
        "fetch_latest": "fetch_latest",
        "summarize": "summarize",
        "help_response": "help_response",
        "greeting_response": "greeting_response",
        "chat_response": "chat_response",
        "test_llm": "test_llm",
        "learn_research": "learn_research",
        "codereview_fetch": "codereview_fetch",
        "digest": "digest",
        "duplicate_check": "duplicate_check",
        "release_notes": "release_notes",
        "search": "search",
    })

    g.add_edge("parse_reminder", "schedule_reminder")
    g.add_edge("schedule_reminder", END)
    g.add_edge("reminder_list", END)
    g.add_edge("reminder_cancel", END)
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

    # Learn flow: research → structure → resources → response
    g.add_edge("learn_research", "learn_structure")
    g.add_edge("learn_structure", "learn_resources")
    g.add_edge("learn_resources", "learn_response")
    g.add_edge("learn_response", END)

    # Code review flow: fetch → [security, performance, best_practices] → merge → response
    g.add_conditional_edges("codereview_fetch", route_codereview)
    g.add_edge("codereview_security", "codereview_merge")
    g.add_edge("codereview_performance", "codereview_merge")
    g.add_edge("codereview_best_practices", "codereview_merge")
    g.add_edge("codereview_merge", "codereview_response")
    g.add_edge("codereview_response", END)

    # New feature flows
    g.add_edge("digest", END)
    g.add_edge("duplicate_check", END)
    g.add_edge("release_notes", END)
    g.add_edge("search", END)

    return g.compile()


sab_graph = build_graph()
