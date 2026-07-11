import re
import difflib
from .state import BotState, ActionContext, ReminderData
from services.github_service import (
    fetch_github_issue, detect_github_refs,
    fetch_latest_issues, fetch_latest_prs,
    fetch_repo_issues, fetch_repo_prs,
    extract_repo_from_text, find_similar_issues,
)
from services.reminder_service import schedule_reminder, list_reminders, cancel_reminder
from services.llm_service import generate_reply, summarize_thread_messages
from services.learn_service import research_topic, structure_learning_path, curate_resources
from services.codereview_service import (
    parse_review_ref, fetch_pr_diff,
    review_security, review_performance, review_best_practices,
    merge_reviews,
)


_COMMAND_ALIASES = {
    "codereview": "codereview", "coderview": "codereview", "code": "codereview",
    "review": "codereview", "pr": "codereview",
    "learn": "learn",
}


def _match_command(first_word: str) -> str | None:
    if first_word in _COMMAND_ALIASES:
        return _COMMAND_ALIASES[first_word]
    close = difflib.get_close_matches(first_word, _COMMAND_ALIASES.keys(), n=1, cutoff=0.75)
    return _COMMAND_ALIASES[close[0]] if close else None


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

    # Typo-tolerant command matching (catches "coderview", "review", "code", etc.)
    first_word = raw_lower.split()[0] if raw_lower.split() else ""
    matched = _match_command(first_word)
    if matched:
        state["command_type"] = matched
        if matched == "learn":
            state["learn_topic"] = re.sub(r'^\w+\s*', '', state["raw_input"].strip()).strip()
        return state

    # test / test llm
    if re.match(r'^test(?:\s+llm)?$', raw_lower):
        state["command_type"] = "test_llm"
        return state

    # learn command: learn <topic>
    if re.match(r'^learn\b', raw_lower):
        state["command_type"] = "learn"
        topic = re.sub(r'^learn\s*', '', state["raw_input"].strip(), flags=re.IGNORECASE).strip()
        state["learn_topic"] = topic
        return state

    # codereview command: codereview <ref>
    if re.match(r'^codereview\b', raw_lower):
        state["command_type"] = "codereview"
        return state

    # summarize keyword — catch summarize/summarise/summraise/typos + trailing words
    if re.search(r'\bsum+ar\w*\b|\bsum+ra\w*\b', raw_lower):
        state["command_type"] = "context"
        state["needs_llm"] = True
        return state

    # reminders list/cancel — must come before reminder to avoid regex overlap
    if re.search(r'\breminders?\b', raw_lower):
        if re.search(r'\b(cancel|delete|remove)\b', raw_lower):
            state["command_type"] = "reminder_cancel"
        else:
            state["command_type"] = "reminder_list"
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

    # digest subscribe/unsubscribe/demo
    if re.match(r'^digest\b', raw_lower):
        state["command_type"] = "digest"
        return state

    # duplicate issue detection
    if re.match(r'^duplicate\b', raw_lower):
        state["command_type"] = "duplicate"
        return state

    # release notes generator
    if re.search(r'\brelease\s+notes?\b', raw_lower):
        state["command_type"] = "release_notes"
        return state

    # real-time search: /sab search <query> or @bot find discussions about X
    if re.match(r'^search\b', raw_lower):
        state["command_type"] = "search"
        state["search_query"] = re.sub(r'^search\s*', '', state["raw_input"].strip(), flags=re.IGNORECASE).strip()
        return state
    search_nl = re.search(
        r'(?:find|search)\s+(?:discussions?|messages?|threads?|conversations?)\s+(?:about|on|for)\s+(.+)',
        raw_lower,
    )
    if search_nl:
        state["command_type"] = "search"
        state["search_query"] = search_nl.group(1).strip()
        return state

    # help intent — must come before greeting_words to prevent misrouting
    HELP_PHRASES = {
        "help", "what can you do", "what do you do", "who are you",
        "commands", "list commands", "show commands", "menu",
    }
    if raw_lower in HELP_PHRASES:
        state["command_type"] = "help"
        return state

    # exact greeting words only
    greeting_words = {
        "hi", "hey", "hello", "hlo", "hlw", "heu", "hii", "heyy",
        "yo", "sup", "gm", "gn", "bye", "thanks", "thank", "cheers",
        "howdy", "greetings", "welcome",
        "how are u", "how are you", "whats up", "what's up",
        "good morning", "good night",
        "ping", "pong",
    }

    if raw_lower in greeting_words:
        state["command_type"] = "greeting"
        return state

    # GitHub PR URL → codereview (parse_review_ref already handles URL format)
    if re.search(r'github\.com/[\w-]+/[\w-]+/pull/\d+', raw_lower):
        state["command_type"] = "codereview"
        return state

    # GitHub issue URL → github lookup
    if re.search(r'github\.com/[\w-]+/[\w-]+/issues/\d+', raw_lower):
        state["command_type"] = "github"
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
        # Fallback: try dateparser for natural language like "remind me tomorrow at 3pm"
        try:
            import dateparser
            from datetime import datetime

            # Extract the task text — strip common prefixes
            task_text = re.sub(
                r'\b(remind\s+me\s+to\s+|remind\s+me\s+|remind\s+)',
                '', text, flags=re.IGNORECASE
            ).strip()

            # Pre-normalize "X mins later" → "in X minutes" for dateparser
            task_text = re.sub(
                r'\b(?:in\s+)?(\d+)\s*(min(?:ute)?s?|hours?|hrs?)\s+later\b',
                r'in \1 \2', task_text, flags=re.IGNORECASE
            )

            # Let dateparser find the time expression
            parsed_time = dateparser.parse(
                task_text,
                settings={
                    'PREFER_DATES_FROM': 'future',
                },
            )

            if parsed_time:
                now = datetime.now()
                delay_seconds = int((parsed_time - now).total_seconds())
                if delay_seconds > 0:
                    reminder_text = re.sub(
                        r'\b(in \d+ \w+|tomorrow|next \w+|at \d+:\d+|\d+ (?:hours?|minutes?|mins?|hrs?)\w*)',
                        '', task_text, flags=re.IGNORECASE
                    ).strip().rstrip('to ').strip()
                    reminder_text = re.sub(
                        r'^\s*(me\s+to\s+|to\s+)', '', reminder_text, flags=re.IGNORECASE
                    ).strip()
                    if not reminder_text:
                        reminder_text = task_text

                    state["reminder_data"] = ReminderData(
                        text=reminder_text,
                        delay_seconds=delay_seconds,
                        user_id=state["user_id"],
                        channel_id=state["channel_id"],
                    )
                    return state
        except Exception:
            pass

        state["response_message"] = (
            "Could not parse reminder. Use format:\n"
            "• `/sab -r \"task\" @30m`\n"
            "• `/sab remind me to call mom @1h`\n"
            "• `/sab remind me to check server tomorrow at 3pm`"
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


def reminder_list_node(state: BotState) -> BotState:
    """List all pending reminders for the user."""
    user_id = state.get("user_id", "")
    reminders = list_reminders(user_id)
    if reminders:
        parts = ["*Your pending reminders:*\n"]
        for r in reminders:
            parts.append(f"• `{r['id']}` — {r['text']} (at {r['run_time']})")
        parts.append("\nTo cancel: `/sab reminder cancel <id>`")
        state["response_message"] = "\n".join(parts)
    else:
        state["response_message"] = "No pending reminders. Set one with `/sab -r \"task\" @30m`"
    return state


def reminder_cancel_node(state: BotState) -> BotState:
    """Cancel a pending reminder by ID."""
    raw = state.get("raw_input", "")
    # Extract job ID from the message — capture alphanumeric + underscores, strip stray characters
    match = re.search(r'(?:cancel|delete|remove)\s+([a-zA-Z0-9_<>`]+)', raw, re.IGNORECASE)
    if match:
        job_id = match.group(1).strip('`<>')
        # Accept short suffix (e.g., "abc123") and auto-prefix
        if not job_id.startswith("reminder_"):
            job_id = f"reminder_{job_id}"
        if cancel_reminder(job_id):
            state["response_message"] = f"Reminder `{job_id}` cancelled."
        else:
            state["response_message"] = f"Could not find reminder `{job_id}`. Run `/sab reminders` to see pending ones."
    else:
        state["response_message"] = (
            "Which reminder to cancel? Run `/sab reminders` to see IDs, then:\n"
            "`/sab reminder cancel <id>`"
        )
    return state


def summarize_action(state: BotState) -> BotState:
    if not state.get("needs_llm"):
        return state

    thread_messages = state.get("thread_messages", [])
    max_messages = state.get("max_messages", 25)

    if thread_messages:
        summary = summarize_thread_messages(thread_messages, max_messages)
        state["llm_summary"] = summary
        state["response_message"] = summary
        return state

    # No thread context supplied: summarize the channel via the Slack MCP server.
    channel_id = state.get("channel_id")
    if channel_id:
        from services.slack_summarize_service import summarize_slack

        result = summarize_slack(channel_id)
        if result.get("error"):
            state["response_message"] = result["error"]
        else:
            msg = result["summary"]
            if result.get("warning"):
                msg = f"{result['warning']}\n\n{msg}"
            state["llm_summary"] = result["summary"]
            state["response_message"] = msg
        return state

    state["response_message"] = (
        "It looks like this channel's recent activity is mostly bot replies or commands — "
        "I need some actual conversation to summarize. Try it in a thread with real back-and-forth, "
        "or chat a bit first!"
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
    state["response_message"] = (
        "*I'm SAB — your Slack Actions Bot.* Here's everything I can do:\n\n"
        "*📝 Summarize*\n"
        "• `/sab summarize` (in a thread or channel) — summarizes up to 25 recent messages\n"
        "• Just say \"summarize\" or \"catch me up\" — same thing\n\n"
        "*⏰ Reminders*\n"
        "• `/sab -r \"task\" @30m` — reminder in 30 min (also `@2h` for hours)\n"
        "• `/sab remind me to check the server tomorrow at 3pm` — natural language works too\n"
        "• `/sab reminders` — list pending reminders\n"
        "• `/sab reminder cancel <id>` — cancel a pending reminder\n\n"
        "*🔍 GitHub lookups*\n"
        "• Mention `owner/repo#123` — pulls up that issue or PR\n"
        "• Paste a GitHub PR/issue link directly — same result\n"
        "• `/sab latest issues` / `/sab latest prs` — newest open items\n\n"
        "*🛠️ Code review*\n"
        "• `/sab codereview owner/repo#123` — security, performance, and best-practices review\n"
        "• Works with a pasted PR link too\n\n"
        "*📚 Learn*\n"
        "• `/sab learn <topic>` — a structured learning path with resources\n\n"
        "*📅 Daily Digest*\n"
        "• `/sab digest subscribe` — daily GitHub issues/PRs at 9am UTC\n"
        "• `/sab digest demo` — preview digest in ~2 minutes\n"
        "• `/sab digest unsubscribe` — cancel digest\n\n"
        "*🔎 Duplicate Check*\n"
        "• `/sab duplicate owner/repo \"issue title\"` — find similar open issues\n\n"
        "*📋 Release Notes*\n"
        "• `/sab release notes owner/repo` — generate notes from merged PRs\n\n"
        "*🔍 Workspace Search*\n"
        "• `@bot find discussions about <topic>` — search all channels (needs search:read scope)\n"
        "• `/sab search <query>` — same, but @mention works best (action_token required)\n\n"
        "*🩺 Diagnostics*\n"
        "• `/sab test` — checks LLM provider + MCP health\n\n"
        "@mention me anytime, or use `/sab` — I'll figure out what you need."
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
    from services.llm_service import check_local_llm, check_gemini_llm
    from services.mcp_client import mcp_client
    from config import LLM_PROVIDER, LLM_FALLBACK_ENABLED, GOOGLE_API_KEY

    llm_ok = check_local_llm()
    gemini_ok = check_gemini_llm() if GOOGLE_API_KEY else False
    mcp_status = {name: mcp_client.health_check(name) for name in ("github", "fetch", "slack")}

    primary = LLM_PROVIDER if LLM_PROVIDER in ("local", "gemini") else "local"
    fallback_label = "enabled" if LLM_FALLBACK_ENABLED else "disabled"
    lines = [f"Provider: {primary} (primary) · Fallback: {fallback_label}\n"]
    lines.append(f"{'✓' if llm_ok else '✗'} Local LLM (Qwen3-8B)")
    if GOOGLE_API_KEY:
        lines.append(f"{'✓' if gemini_ok else '✗'} Gemini API")
    lines += [f"{'✓' if ok else '✗'} MCP: {name}" for name, ok in mcp_status.items()]

    all_ok = (llm_ok if primary == "local" else gemini_ok) and all(mcp_status.values())
    if all_ok:
        lines.insert(1, "All systems operational\n")
    else:
        failed = [name for name, ok in mcp_status.items() if not ok]
        hint = []
        if primary == "local" and not llm_ok:
            hint.append("llama-server running on port 8080 with -c 16384?")
        if primary == "gemini" and not gemini_ok:
            hint.append("GOOGLE_API_KEY valid?")
        if failed:
            hint.append(f"MCP ({', '.join(failed)}) connected?")
        lines.append(f"\nHint: Check {' & '.join(hint)}")

    state["response_message"] = "\n".join(lines)
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
    state["learn_via_mcp"] = result.get("search_via_mcp", False)
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
    summary = curate_resources(
        topic, resources, path,
        search_via_mcp=state.get("learn_via_mcp", False),
    )
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

    if pr_number is None:
        state["response_message"] = (
            f"`{repo}` is a repo, not a specific PR — I can only review one PR at a time.\n"
            f"Try `/sab codereview {repo}#123`, or run `/sab latest prs {repo}` "
            f"to see open PRs to pick a number from."
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

    if not pr_data.get("files"):
        state["review_warning"] = (
            f"Fetched PR metadata for *{pr_data.get('title', 'Unknown')}* but no file diffs "
            f"were available. Review will be based on title/description only — results may be limited."
        )
        # fall through, continue with shallow review

    state["review_via_mcp"] = pr_data.get("via_mcp", False)
    state["review_pr_data"] = pr_data
    return state


def codereview_security(state: BotState) -> dict:
    """Security reviewer subagent."""
    pr_data = state.get("review_pr_data", {})
    print(f"[CodeReview] Security review for: {pr_data.get('title', 'Unknown')}")
    from services.codereview_service import _run_semgrep
    semgrep_findings = _run_semgrep(pr_data)
    result = review_security(pr_data, semgrep_findings)
    return {"review_security": result, "review_semgrep_findings": semgrep_findings}


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
    warning = state.get("review_warning", "")
    via_mcp = state.get("review_via_mcp", False)
    semgrep_findings = state.get("review_semgrep_findings", [])

    print("[CodeReview] Merging reviews")
    merged = merge_reviews(security, performance, best_practices, pr_data,
                           via_mcp=via_mcp, semgrep_findings=semgrep_findings)
    if warning:
        merged = f"{warning}\n\n{merged}"
    state["response_message"] = merged
    return state


def codereview_response(state: BotState) -> BotState:
    """Ensure response is set."""
    if not state.get("response_message"):
        state["response_message"] = "Code review completed. Try `/sab codereview owner/repo#123`"
    return state


# ============================================================
# Digest Command Node
# ============================================================

def digest_node(state: BotState) -> BotState:
    from services.reminder_service import (
        schedule_daily_digest, cancel_daily_digest, schedule_digest_demo,
    )
    raw = state.get("raw_input", "").lower()
    channel_id = state.get("channel_id", "")

    if "unsubscribe" in raw or "cancel" in raw:
        ok = cancel_daily_digest(channel_id)
        state["response_message"] = (
            "Daily digest cancelled." if ok
            else "No digest was subscribed for this channel."
        )
    elif "demo" in raw:
        schedule_digest_demo(channel_id, delay_minutes=2)
        state["response_message"] = "Demo digest scheduled — posting in ~2 minutes."
    elif "subscribe" in raw:
        schedule_daily_digest(channel_id)
        state["response_message"] = (
            "Daily digest subscribed — posts at 9:00 UTC in this channel."
        )
    else:
        state["response_message"] = (
            "Usage: `/sab digest subscribe`, `digest unsubscribe`, or `digest demo`"
        )
    return state


# ============================================================
# Duplicate Check Node
# ============================================================

def duplicate_check_node(state: BotState) -> BotState:
    raw = state.get("raw_input", "")
    repo = extract_repo_from_text(raw)
    title_match = re.search(r'"([^"]+)"', raw) or re.search(r"'([^']+)'", raw)

    if not repo or not title_match:
        state["response_message"] = (
            "Usage: `/sab duplicate owner/repo \"issue title to check\"`"
        )
        return state

    matches = find_similar_issues(repo, title_match.group(1))
    if not matches:
        state["response_message"] = f"No likely duplicates found in `{repo}`."
        return state

    lines = [f"*Possible duplicates in {repo}:*"]
    for m in matches:
        pct = int(m["score"] * 100)
        lines.append(f"• {pct}% — \"{m['title']}\" <{m['url']}|#{m['number']}>")
    state["response_message"] = "\n".join(lines)
    return state


# ============================================================
# Release Notes Node
# ============================================================

def release_notes_node(state: BotState) -> BotState:
    from services.release_service import generate_release_notes

    repo = extract_repo_from_text(state.get("raw_input", ""))
    if not repo:
        state["response_message"] = "Usage: `/sab release notes owner/repo`"
        return state

    state["response_message"] = generate_release_notes(repo)
    return state


# ============================================================
# Real-Time Search Node
# ============================================================

def search_node(state: BotState) -> BotState:
    from services.slack_search_service import search_slack_context, summarize_search_results

    query = state.get("search_query", "").strip()
    if not query:
        state["response_message"] = (
            "Usage:\n"
            "• `@bot find discussions about deployment`\n"
            "• `/sab search deployment planning`\n\n"
            "_Note: Real-time search works best via @mention (requires `search:read` scope)._"
        )
        return state

    action_token = state.get("action_token", "")
    result = search_slack_context(action_token, query)

    if result.get("error"):
        state["response_message"] = result["error"]
        return state

    state["response_message"] = summarize_search_results(query, result.get("messages", []))
    return state
