import re
from datetime import datetime
from typing import Optional
from .state import BotState, ActionContext, ReminderData
from services.github_service import fetch_github_issue, detect_github_refs
from services.reminder_service import schedule_reminder
from services.llm_service import summarize_context
from config import DEFAULT_GITHUB_REPO


def classify_intent(state: BotState) -> BotState:
    raw = state["raw_input"].lower().strip()

    if "-r" in raw or re.search(r'\bremind\b', raw):
        state["command_type"] = "reminder"
        return state

    ctx = state.get("action_context")
    if ctx and isinstance(ctx, ActionContext):
        if not raw or raw == "/sab":
            state["command_type"] = "mention"
            return state
        if ctx.original_message:
            github_pattern = r"(?:[\w-]+/[\w-]+)?#\d+"
            if re.search(github_pattern, raw):
                state["command_type"] = "github"
            else:
                state["command_type"] = "context"
                state["needs_llm"] = True
            return state
        state["command_type"] = "mention"
        return state

    github_pattern = r"(?:[\w-]+/[\w-]+)?#\d+"
    if re.search(github_pattern, raw):
        state["command_type"] = "github"
        return state

    state["command_type"] = "unknown"
    return state


def extract_github_refs(state: BotState) -> BotState:
    refs = detect_github_refs(state["raw_input"])
    state["github_refs"] = refs
    return state


def fetch_github_issues(state: BotState) -> BotState:
    results = []
    for ref in state.get("github_refs", []):
        parts = ref.split("#")
        if len(parts) != 2:
            continue
        repo = parts[0]
        try:
            issue_num = int(parts[1])
        except ValueError:
            continue
        issue_data = fetch_github_issue(repo, issue_num)
        if issue_data:
            results.append(issue_data)
    state["github_results"] = results
    return state


def parse_reminder(state: BotState) -> BotState:
    text = state["raw_input"]
    match = re.search(r'-r\s"([^"]+?)"\s@(\d+)([mh])', text)

    if not match:
        match = re.search(r"-r\s(.+?)@(\d+)([mh])", text)

    if match:
        reminder_text = match.group(1).strip()
        time_value = int(match.group(2))
        time_unit = match.group(3)
        delay = time_value * 60 if time_unit == "m" else time_value * 3600

        state["reminder_data"] = ReminderData(
            text=reminder_text,
            delay_seconds=delay,
            user_id=state["user_id"],
            channel_id=state["channel_id"],
        )
    else:
        state["response_message"] = (
            "Could not parse reminder. Use format: `/sab -r \"task\" @30m`"
        )
    return state


def schedule_reminder_node(state: BotState) -> BotState:
    reminder = state.get("reminder_data")
    if reminder:
        schedule_reminder(
            user_id=reminder.user_id,
            text=reminder.text,
            delay_seconds=reminder.delay_seconds,
            channel_id=reminder.channel_id,
        )
        h = reminder.delay_seconds // 3600
        m = (reminder.delay_seconds % 3600) // 60
        time_str = f"{h}h{m}m" if h else f"{m}m"
        state["response_message"] = f"Reminder set: '{reminder.text}' in {time_str}"
    elif not state.get("response_message"):
        state["response_message"] = "Failed to schedule reminder."
    return state


def summarize_action(state: BotState) -> BotState:
    if state.get("needs_llm"):
        ctx = state.get("action_context")
        if ctx and isinstance(ctx, ActionContext) and ctx.original_message:
            summary = summarize_context(ctx.original_message, state["raw_input"])
            state["llm_summary"] = summary
            state["response_message"] = summary
    return state


def build_context_response(state: BotState) -> BotState:
    ctx = state.get("action_context")
    if ctx and isinstance(ctx, ActionContext):
        parts = []
        if ctx.mentioned_by:
            parts.append(f"*Who mentioned you:* <@{ctx.mentioned_by}>")
        if ctx.original_message:
            parts.append(f"*Original message:*\n> {ctx.original_message}")
        parts.append("Use `/sab` to summarize or set a reminder.")
        state["response_message"] = "\n".join(parts)
    return state


def build_github_response(state: BotState) -> BotState:
    results = state.get("github_results", [])
    if results:
        parts = []
        for r in results:
            status = "Open" if r["state"] == "open" else "Closed"
            parts.append(
                f"*{r['title']}*\nStatus: {status}\n<{r['url']}|View on GitHub>"
            )
        state["response_message"] = "\n\n".join(parts)
    else:
        state["response_message"] = "Could not fetch GitHub issue/PR details."
    return state


def build_mention_response(state: BotState) -> BotState:
    ctx = state.get("action_context")
    if ctx:
        state["response_message"] = (
            f"Hi <@{state['user_id']}>! Someone mentioned you.\n"
            f"Reply with `/sab` to handle this action."
        )
    return state


def build_unknown_response(state: BotState) -> BotState:
    state["response_message"] = (
        "I can help you with:\n"
        "• `/sab` — Capture action context\n"
        "• `/sab -r \"task\" @30m` — Set a reminder\n"
        "• Mention `#123` or `org/repo#456` for GitHub info"
    )
    return state
