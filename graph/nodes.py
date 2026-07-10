import re
from .state import BotState, ActionContext, ReminderData
from services.github_service import (
    fetch_github_issue, detect_github_refs,
    fetch_latest_issues, fetch_latest_prs,
    fetch_repo_issues, fetch_repo_prs,
    extract_repo_from_text,
)
from services.reminder_service import schedule_reminder
from services.llm_service import generate_reply, summarize_thread_messages
from services.learn_service import research_topic, structure_learning_path, curate_resources
from services.codereview_service import (
    parse_review_ref, fetch_pr_diff,
    review_security, review_performance, review_best_practices,
    merge_reviews,
)


def classify_intent(state: BotState) -> BotState:
    raw = state["raw_input"].strip()

    # Empty input: check if we have thread/channel messages to summarize
    if not raw:
        thread_messages = state.get("thread_messages", [])
        if thread_messages:
            state["command_type"] = "context"
            state["needs_llm"] = True
            return state
        else:
            state["command_type"] = "help"
            return state

    raw_lower = raw.lower().strip()

    # test / test llm
    if re.match(r'^test(?:\s+llm)?$', raw_lower):
        state["command_type"] = "test_llm"
        return state

    # learn command: learn <topic>
    if re.match(r'^learn\b', raw_lower):
        state["command_type"] = "learn"
        # Extract topic after "learn"
        topic = re.sub(r'^learn\s*', '', state["raw_input"].strip(), flags=re.IGNORECASE).strip()
        state["learn_topic"] = topic
        return state

    # codereview command: codereview <ref>
    if re.match(r'^codereview\b', raw_lower):
        state["command_type"] = "codereview"
        return state

    # explicit summarize keyword - always route to context
    if re.match(r'^summarize?$', raw_lower):
        state["command_type"] = "context"
        state["needs_llm"] = True
        return state

    # reminder: -r "task"@30m  OR  remind me to ...
    if re.search(r'(?:^|\s)-r\b', raw_lower) or re.search(r'\bremind(?:er|ed|ing)?\b', raw_lower):
        state["command_type"] = "reminder"
        return state

    # latest issues/prs
    if re.search(r'\b(?:latest|recent|list)\b', raw_lower):
        if re.search(r'\b(?:issues?|prs?|pull)\b', raw_lower):
            state["command_type"] = "latest_github"
            return state

    # exact greeting words only
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

    # GitHub ref: owner/repo#123 (bare #123 not supported — no default repo)
    if re.search(r'\b[\w-]+/[\w-]+#\d+\b', raw_lower):
        state["command_type"] = "github"
        return state

    # Thread context: only if there are actual thread messages to summarize
    thread_messages = state.get("thread_messages", [])
    if thread_messages:
        state["command_type"] = "context"
        state["needs_llm"] = True
        return state

    # Default: chat
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

    # Check if user specified a repo (handles URLs and plain text)
    specific_repo = extract_repo_from_text(state["raw_input"])

    is_pr = re.search(r'\b(?:prs?|pull)\b', raw_lower) and not re.search(r'\bprint\b', raw_lower)

    if specific_repo:
        if is_pr:
            results = fetch_repo_prs(specific_repo, count=5)
        else:
            results = fetch_repo_issues(specific_repo, count=5)
    else:
        if is_pr:
            results = fetch_latest_prs(count=5)
        else:
            results = fetch_latest_issues(count=5)

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
        reminder_text = match.group(1).strip().strip('"')
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
        max_messages = state.get("max_messages", 25)

        if thread_messages:
            summary = summarize_thread_messages(thread_messages, max_messages)
            state["llm_summary"] = summary
            state["response_message"] = summary
        else:
            state["response_message"] = (
                "No messages to summarize. I need `channels:history` permission "
                "to read channel messages. Ask your Slack admin to add it in "
                "the app settings under OAuth & Permissions."
            )
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
    else:
        state["response_message"] = "No context available."
    return state


def build_github_response(state: BotState) -> BotState:
    results = state.get("github_results", [])
    if results:
        parts = []
        for r in results:
            status = "Open" if r["state"] == "open" else "Closed"
            item_type = r.get("type", "Issue")
            repo = r.get("repo", "")
            parts.append(
                f"*[{item_type} #{r['number']}] {r['title']}*\n"
                f"Repo: {repo}\n"
                f"Status: {status}\n<{r['url']}|View on GitHub>"
            )
        state["response_message"] = "\n\n".join(parts)
    else:
        state["response_message"] = (
            "Could not fetch GitHub issues/PRs. Check:\n"
            "• `GITHUB_TOKEN` is set in `.env`\n"
            "• Token has `repo` scope\n"
            "• Repo name is correct (owner/repo)"
        )
    return state


def build_help_response(state: BotState) -> BotState:
    reply = generate_reply("What can you do? List your commands.")
    state["response_message"] = reply if reply else (
        "I can help with:\n"
        "• Summarize messages — just mention me or say `summarize`\n"
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


# ============================================================
# Learn Command Nodes
# ============================================================

def learn_research(state: BotState) -> BotState:
    """Research agent: Gather resources about the topic."""
    topic = state.get("learn_topic", "").strip()
    if not topic:
        state["response_message"] = (
            "Please specify a topic to learn.\n"
            "Example: `/sab learn python async programming`"
        )
        return state

    print(f"[Learn] Researching topic: {topic}")
    result = research_topic(topic)
    state["learn_resources"] = result.get("resources", [])
    return state


def learn_structure(state: BotState) -> BotState:
    """Structure agent: Organize by skill level."""
    # Skip if error already set
    if state.get("response_message"):
        return state

    topic = state.get("learn_topic", "")
    resources = state.get("learn_resources", [])

    print(f"[Learn] Structuring learning path for: {topic}")
    path = structure_learning_path(topic, resources)
    state["learn_path"] = path
    return state


def learn_resources(state: BotState) -> BotState:
    """Resource agent: Finalize with curated resources."""
    # Skip if error already set
    if state.get("response_message"):
        return state

    topic = state.get("learn_topic", "")
    resources = state.get("learn_resources", [])
    path = state.get("learn_path", {})

    print(f"[Learn] Curating resources for: {topic}")
    summary = curate_resources(topic, resources, path)
    state["response_message"] = summary
    return state


def learn_response(state: BotState) -> BotState:
    """Ensure response is set."""
    if not state.get("response_message"):
        state["response_message"] = "Learning path generated. Try `/sab learn <topic>` to get started."
    return state


# ============================================================
# Code Review Command Nodes
# ============================================================

def codereview_fetch(state: BotState) -> BotState:
    """Fetch PR diff via GitHub MCP."""
    raw = state.get("raw_input", "")
    ref = parse_review_ref(raw)

    if not ref:
        state["response_message"] = (
            "Could not parse PR reference. Use format:\n"
            "• `/sab codereview owner/repo#123`\n"
            "• `/sab codereview https://github.com/owner/repo/pull/123`"
        )
        return state

    repo = ref.get("repo")
    pr_number = ref.get("pr_number")

    if not repo:
        state["response_message"] = (
            "Please specify a repo. Use format:\n"
            "• `/sab codereview owner/repo#123`\n"
            "• `/sab codereview https://github.com/owner/repo/pull/123`"
        )
        return state

    print(f"[CodeReview] Fetching PR {repo}#{pr_number}")
    pr_data = fetch_pr_diff(repo, pr_number)

    # Check if fetch failed
    if pr_data.get("title") == "Unknown PR":
        state["response_message"] = (
            "Could not fetch PR data. Check:\n"
            "• Repo name is correct (owner/repo)\n"
            "• PR number exists\n"
            "• GITHUB_TOKEN has access"
        )
        return state

    state["review_pr_data"] = pr_data
    return state


def codereview_security(state: BotState) -> dict:
    """Security reviewer subagent."""
    pr_data = state.get("review_pr_data", {})
    print(f"[CodeReview] Security review for: {pr_data.get('title', 'Unknown')}")
    return {"review_security": review_security(pr_data)}


def codereview_performance(state: BotState) -> dict:
    """Performance reviewer subagent."""
    pr_data = state.get("review_pr_data", {})
    print(f"[CodeReview] Performance review for: {pr_data.get('title', 'Unknown')}")
    return {"review_performance": review_performance(pr_data)}


def codereview_best_practices(state: BotState) -> dict:
    """Best practices reviewer subagent."""
    pr_data = state.get("review_pr_data", {})
    print(f"[CodeReview] Best practices review for: {pr_data.get('title', 'Unknown')}")
    return {"review_best_practices": review_best_practices(pr_data)}


def codereview_merge(state: BotState) -> BotState:
    """Merge all three review outputs."""
    security = state.get("review_security", "")
    performance = state.get("review_performance", "")
    best_practices = state.get("review_best_practices", "")
    pr_data = state.get("review_pr_data", {})

    print("[CodeReview] Merging reviews")
    merged = merge_reviews(security, performance, best_practices, pr_data)
    state["response_message"] = merged
    return state


def codereview_response(state: BotState) -> BotState:
    """Ensure response is set."""
    if not state.get("response_message"):
        state["response_message"] = "Code review completed. Try `/sab codereview owner/repo#123`"
    return state
