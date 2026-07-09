import re
from .state import BotState, ActionContext, ReminderData
from services.github_service import (
    fetch_github_issue, detect_github_refs,
    fetch_latest_issues, fetch_latest_prs,
)
from services.reminder_service import schedule_reminder
from services.llm_service import generate_reply, summarize_context, summarize_thread_messages
from config import DEFAULT_GITHUB_REPO

_REPO_PATTERN = re.compile(r'^[\w][\w.-]*/[\w][\w.-]*$')


def classify_intent(state: BotState) -> BotState:
    raw = state["raw_input"].strip()

    if not raw:
        ctx = state.get("action_context")
        if ctx and state.get("thread_messages"):
            state["command_type"] = "context"
            state["needs_llm"] = True
        else:
            state["command_type"] = "help"
        return state

    raw_lower = raw.lower().strip()

    if re.match(r'^test(?:\s+llm)?$', raw_lower):
        state["command_type"] = "test_llm"
        return state

    if re.search(r'(?:^|\s)-r\b', raw_lower) or re.search(r'\bremind(?:er|ed|ing)?\b', raw_lower):
        state["command_type"] = "reminder"
        return state

    if re.search(r'\b(?:latest|recent|list)\b', raw_lower):
        if re.search(r'\b(?:issues?|prs?|pull)\b', raw_lower):
            state["command_type"] = "latest_github"
            return state

    greeting_words = {
        "hi", "hey", "hello", "hlo", "hlw", "heu", "hii", "heyy",
        "yo", "sup", "gm", "gn", "bye", "thanks", "thank", "cheers",
        "howdy", "greetings", "welcome",
        "how are u", "how are you", "whats up", "what's up",
        "good morning", "good night",
        "what can you do", "what do you do", "who are you",
        "ping", "pong",
    }

    if raw_lower in greeting_words:
        state["command_type"] = "greeting"
        return state

    if re.search(r'\b(?:[\w-]+/[\w-]+)?#\d+\b', raw_lower):
        state["command_type"] = "github"
        return state

    ctx = state.get("action_context")
    if ctx and isinstance(ctx, ActionContext):
        state["command_type"] = "context"
        state["needs_llm"] = True
        return state

    state["command_type"] = "chat"
    return state


def extract_github_refs(state: BotState) -> BotState:
    state["github_refs"] = detect_github_refs(state["raw_input"])
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


def fetch_latest_github_items(state: BotState) -> BotState:
    raw_lower = state["raw_input"].lower()
    repo = DEFAULT_GITHUB_REPO

    repo_match = re.search(r'(\w[\w.-]*/\w[\w.-]*)', state["raw_input"])
    if repo_match and _REPO_PATTERN.match(repo_match.group(1)):
        repo = repo_match.group(1)

    results = []
    if re.search(r'\b(?:prs?|pull)\b', raw_lower) and not re.search(r'\bprint\b', raw_lower):
        prs = fetch_latest_prs(repo, count=5)
        for pr in prs:
            results.append({
                "title": pr["title"],
                "state": pr["state"],
                "url": pr["url"],
                "number": pr["number"],
                "repo": repo,
                "type": "PR",
            })
    else:
        issues = fetch_latest_issues(repo, count=5)
        for issue in issues:
            results.append({
                "title": issue["title"],
                "state": issue["state"],
                "url": issue["url"],
                "number": issue["number"],
                "repo": repo,
                "type": "Issue",
            })

    state["github_results"] = results
    return state


def parse_reminder(state: BotState) -> BotState:
    text = state["raw_input"]
    match = re.search(r'-r\s+"([^"]+?)"\s+@(\d+)([mh])', text)

    if not match:
        match = re.search(r'-r\s+"([^"]+?)"@(\d+)([mh])', text)

    if not match:
        match = re.search(r'-r\s+([^@]+?)\s*@(\d+)([mh])', text)

    if not match:
        match = re.search(r'\bremind\b.*?[""]?([^""@]+?)[""]?\s*@(\d+)([mh])', text, re.IGNORECASE)

    if match:
        reminder_text = match.group(1).strip().strip('""')
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
        time_str = f"{h}h {m}m" if h else f"{m}m"
        state["response_message"] = f"Reminder set: '{reminder.text}' in {time_str}"
    elif not state.get("response_message"):
        state["response_message"] = "Failed to schedule reminder."
    return state


def summarize_action(state: BotState) -> BotState:
    if state.get("needs_llm"):
        thread_messages = state.get("thread_messages", [])
        max_messages = state.get("max_messages", 10)

        if thread_messages:
            summary = summarize_thread_messages(thread_messages, max_messages)
            state["llm_summary"] = summary
            state["response_message"] = summary
        else:
            ctx = state.get("action_context")
            if ctx and isinstance(ctx, ActionContext) and ctx.original_message:
                summary = summarize_context(ctx.original_message, state["raw_input"])
                state["llm_summary"] = summary
                state["response_message"] = summary
    return state


def build_context_response(state: BotState) -> BotState:
    if state.get("response_message"):
        return state

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
            item_type = r.get("type", "Issue")
            parts.append(
                f"*[{item_type} #{r['number']}] {r['title']}*\n"
                f"Status: {status}\n<{r['url']}|View on GitHub>"
            )
        state["response_message"] = "\n\n".join(parts)
    else:
        state["response_message"] = "Could not fetch GitHub issue/PR details."
    return state


def build_help_response(state: BotState) -> BotState:
    reply = generate_reply("What can you do? List your commands.")
    state["response_message"] = reply if reply else (
        "I can help with:\n"
        "• Summarize messages using AI\n"
        "• `/sab -r \"task\" @30m` — Set reminders\n"
        "• GitHub lookups — mention #123 or org/repo#123\n"
        "• `/sab latest issues` — Fetch latest issues\n"
        "• `/sab latest prs` — Fetch latest PRs\n"
        "• `/sab test` — Test LLM connection"
    )
    return state


def build_greeting_response(state: BotState) -> BotState:
    reply = generate_reply(state["raw_input"].strip())
    state["response_message"] = reply if reply else "Hey there! How can I help you? 👋"
    return state


def build_chat_response(state: BotState) -> BotState:
    reply = generate_reply(state["raw_input"].strip())
    state["response_message"] = reply if reply else "I'm not sure how to help. Try saying hi or /sab for help."
    return state


def test_llm_connection(state: BotState) -> BotState:
    from services.llm_service import _chat_completion
    result = _chat_completion("Say 'LLM is working!' in exactly 5 words or less", max_tokens=20)
    if result:
        state["response_message"] = f"✓ LLM is connected!\nResponse: {result}"
    else:
        state["response_message"] = "✗ LLM connection failed. Check if llama-server is running."
    return state
