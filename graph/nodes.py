import re
from typing import Optional
from .state import BotState, ActionContext, ReminderData
from services.github_service import fetch_github_issue, detect_github_refs, fetch_latest_issues, fetch_latest_prs
from services.reminder_service import schedule_reminder
from services.llm_service import summarize_context, summarize_thread_messages, generate_mention_reply
from config import DEFAULT_GITHUB_REPO


def classify_intent(state: BotState) -> BotState:
    raw = state["raw_input"].lower().strip()

    if raw.startswith("test llm") or raw == "test":
        state["command_type"] = "test_llm"
        return state

    if "-r" in raw or re.search(r'\bremind\b', raw):
        state["command_type"] = "reminder"
        return state

    if re.search(r'\b(latest|recent|list)\b', raw) and re.search(r'\b(issues?|prs?|pull)\b', raw):
        state["command_type"] = "latest_github"
        return state

    greeting_words = [
        r'^hi$', r'^hey$', r'^hello$', r'^hlo$', r'^hlw$', r'^heu$',
        r'^yo$', r'^sup$', r'^gm$', r'^gn$', r'^bye$', r'^thanks?$',
        r'^cheers$', r'^howdy$', r'^greetings$', r'^welcome$',
        r'^how\s+are\s+u$', r'^how\s+are\s+you$',
        r'^what\'?s?\s+up$', r'^good\s+morning$', r'^good\s+night$',
        r'^help$', r'^what\s+can\s+you\s+do$', r'^what\s+do\s+you\s+do$',
        r'^hi\s+bot$', r'^hey\s+bot$', r'^hello\s+bot$',
        r'^hi\s+there$', r'^hey\s+there$', r'^hello\s+there$',
    ]
    
    for pattern in greeting_words:
        if re.match(pattern, raw):
            state["command_type"] = "greeting"
            return state

    ctx = state.get("action_context")
    if ctx and isinstance(ctx, ActionContext):
        if not raw or raw == "/sab":
            if state.get("thread_messages"):
                state["command_type"] = "context"
                state["needs_llm"] = True
            else:
                state["command_type"] = "mention"
            return state
        if ctx.original_message:
            github_pattern = r"(?:[\w-]+/[\w-]+)?#\d+"
            if re.search(github_pattern, raw):
                state["command_type"] = "github"
            else:
                for pattern in greeting_words:
                    if re.match(pattern, raw):
                        state["command_type"] = "greeting"
                        return state
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


def fetch_latest_github_items(state: BotState) -> BotState:
    raw = state["raw_input"].lower()
    repo = DEFAULT_GITHUB_REPO
    
    repo_match = re.search(r'([\w-]+/[\w-]+)', state["raw_input"])
    if repo_match:
        repo = repo_match.group(1)
    
    results = []
    if "pr" in raw or "pull" in raw:
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
                f"*[{item_type} #{r['number']}] {r['title']}*\nStatus: {status}\n<{r['url']}|View on GitHub>"
            )
        state["response_message"] = "\n\n".join(parts)
    else:
        state["response_message"] = "Could not fetch GitHub issue/PR details."
    return state


def build_mention_response(state: BotState) -> BotState:
    ctx = state.get("action_context")
    if ctx:
        context = f"Channel: {state['channel_id']}, User: {state['user_id']}"
        original = ctx.original_message or "No message context"
        reply = generate_mention_reply(context, original)
        state["response_message"] = reply
    return state


def build_unknown_response(state: BotState) -> BotState:
    state["response_message"] = (
        "I can help you with:\n"
        "• `/sab` — Capture action context\n"
        "• `/sab -r \"task\" @30m` — Set a reminder\n"
        "• Mention `#123` or `org/repo#456` for GitHub info\n"
        "• `/sab latest issues` — Fetch latest issues\n"
        "• `/sab latest prs` — Fetch latest PRs\n"
        "• `/sab test` — Test LLM connection\n"
        "• Say hi/hey — Get a greeting!"
    )
    return state


def build_greeting_response(state: BotState) -> BotState:
    from services.llm_service import _chat_completion
    
    user_msg = state["raw_input"].lower().strip()
    
    quick_replies = {
        "hi": "Hey there! 👋 I'm Slack Actions Bot. I can help you with reminders, GitHub lookups, and message summaries. Just ask!",
        "hey": "Hey! 👋 What's up? I can set reminders, fetch GitHub issues, or summarize conversations for you!",
        "hello": "Hello! 👋 I'm your Slack Actions Bot. Need a reminder, GitHub info, or a summary? I got you!",
        "heu": "Hey! 👋 How can I help you today?",
        "hlo": "Hello! 👋 I can help with reminders, GitHub, and more!",
        "hlw": "Hi there! 👋 What can I do for you?",
        "hi bot": "Hey there! 👋 I'm Slack Actions Bot. Ask me anything!",
        "hey bot": "Hey! 👋 What's up? I can help with reminders, GitHub, and summaries!",
        "hello bot": "Hello! 👋 I'm here to help. Try `/sab test` to test my LLM!",
        "how are u": "I'm doing great! 😊 Just a bot, but ready to help you out!",
        "how are you": "I'm awesome! 😊 How can I help you today?",
        "help": "I can help you with:\n• Reminders: `/sab -r \"task\" @30m`\n• GitHub: mention `org/repo#123`\n• Summaries: mention me in a thread\n• Type `test llm` to test my AI!",
        "what can you do": "I can help with:\n• `/sab -r \"task\" @30m` — Set reminders\n• GitHub lookups — mention issues/PRs\n• Thread summaries — mention me in threads\n• Chat with me — just say hi!",
    }
    
    if user_msg in quick_replies:
        state["response_message"] = quick_replies[user_msg]
        return state
    
    prompt = (
        f"You are a friendly Slack bot. A user said: \"{user_msg}\"\n"
        f"Reply in 1 short sentence. Be friendly. Mention you can help with reminders, GitHub, and summaries."
    )
    
    reply = _chat_completion(prompt, max_tokens=60)
    state["response_message"] = reply if reply else "Hey there! 👋 I'm Slack Actions Bot. How can I help you?"
    return state


def test_llm_connection(state: BotState) -> BotState:
    from services.llm_service import _chat_completion
    result = _chat_completion("Say 'LLM is working!' in exactly 5 words or less", max_tokens=20)
    if result:
        state["response_message"] = f"✓ LLM is connected!\nResponse: {result}"
    else:
        state["response_message"] = "✗ LLM connection failed. Check if llama-server is running."
    return state
