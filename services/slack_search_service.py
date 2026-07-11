"""
Slack Real-Time Search Service.

Uses Slack's assistant.search.context API for cross-channel search.
Requires `search:read.public` scope and an action_token from the event payload.

Docs: https://docs.slack.dev/reference/methods/assistant.search.context
"""

import requests
from config import SLACK_BOT_TOKEN
from services.llm_service import _chat_completion


def search_slack_context(action_token: str, query: str) -> dict:
    """Search across all channels the user has access to.

    The action_token is a short-lived token injected into message/app_mention
    event payloads by Slack. It's only valid for the lifetime of that event,
    so it can't be stored or reused — each search needs a fresh event context.

    Auth: bot token goes in Authorization header, action_token in request body.

    Returns:
        {"messages": [...]} on success
        {"error": "..."} on failure
    """
    if not action_token:
        return {
            "error": (
                "No action_token available — real-time search requires an "
                "`action_token` from a Slack message or app_mention event.\n\n"
                "This works best when the bot is @mentioned in a channel. "
                "Add the `search:read.public` scope in your Slack app config "
                "and reinstall to the workspace."
            )
        }

    if not SLACK_BOT_TOKEN:
        return {"error": "SLACK_BOT_TOKEN is not configured."}

    try:
        resp = requests.post(
            "https://slack.com/api/assistant.search.context",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={
                "query": query,
                "content_types": ["messages"],
                "channel_types": ["public_channel", "private_channel", "mpim", "im"],
                "action_token": action_token,
                "include_context_messages": True,
                "limit": 10,
                "sort": "score",
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            messages = data.get("results", {}).get("messages", [])
            return {"messages": messages}
        else:
            error = data.get("error", "unknown_error")
            print(f"[Search] Slack API error: {error}")
            if error == "missing_scope":
                return {
                    "error": (
                        "Your Slack app is missing required search scopes. "
                        "Add `search:read.public`, `search:read.files`, and "
                        "`search:read.users` in your app config under "
                        "OAuth & Permissions, then reinstall to the workspace."
                    )
                }
            if error == "invalid_action_token":
                return {
                    "error": (
                        "The action_token is invalid or expired. "
                        "Try @mentioning the bot again in a channel — "
                        "action_tokens are short-lived and tied to each event."
                    )
                }
            return {"error": f"Search failed: {error}"}
    except Exception as e:
        print(f"[Search] Request failed: {e}")
        return {"error": f"Search request failed: {e}"}


def summarize_search_results(query: str, messages: list[dict]) -> str:
    """Summarize search results using the LLM.

    If no messages found, returns a helpful empty-state message.
    Otherwise, formats messages and lets the LLM summarize key points.
    """
    if not messages:
        return (
            f"No results found for *{query}*.\n\n"
            "Tips:\n"
            "• Try broader or different keywords\n"
            "• Search works best via @mention in a channel\n"
            "• Requires `search:read.public` scope in your Slack app"
        )

    # Format messages for the LLM — use 'content' field from RTS API
    formatted = []
    for msg in messages[:10]:
        author = msg.get("author_name", msg.get("author_user_id", "unknown"))
        channel = msg.get("channel_name", msg.get("channel_id", "unknown"))
        text = msg.get("content", msg.get("text", ""))[:300]
        permalink = msg.get("permalink", "")
        ts = msg.get("message_ts", msg.get("ts", ""))
        is_bot = msg.get("is_author_bot", False)
        bot_tag = " [bot]" if is_bot else ""

        # Include context messages if available
        context_before = ""
        context_after = ""
        ctx = msg.get("context_messages", {})
        if ctx.get("before"):
            before_texts = [m.get("text", "")[:100] for m in ctx["before"][:2]]
            context_before = f"\n  ↳ before: {' | '.join(before_texts)}" if before_texts else ""
        if ctx.get("after"):
            after_texts = [m.get("text", "")[:100] for m in ctx["after"][:2]]
            context_after = f"\n  ↳ after: {' | '.join(after_texts)}" if after_texts else ""

        link_part = f"\n  ↳ <{permalink}|View in Slack>" if permalink else ""
        formatted.append(
            f"[#{channel}] {author}{bot_tag}: {text}"
            f"{context_before}{context_after}{link_part}"
        )

    messages_text = "\n\n".join(formatted)

    summary = _chat_completion(
        f"Summarize these Slack search results for the query: \"{query}\"\n\n"
        f"Results ({len(messages)} messages found):\n{messages_text}\n\n"
        f"Provide:\n"
        f"1. Key themes and topics found\n"
        f"2. Notable messages or decisions\n"
        f"3. A brief summary (2-3 sentences)\n"
        f"Keep it concise and actionable.",
        max_tokens=500,
        system_msg=(
            "You are a Slack search assistant. Summarize search results clearly. "
            "Reference specific messages and channels. Be concise."
        ),
    )

    if summary:
        header = f"*Search Results: {query}* ({len(messages)} messages found)\n\n"
        return header + summary

    # Fallback: just list the raw results
    header = f"*Search Results: {query}* ({len(messages)} messages found)\n\n"
    return header + "\n".join(
        f"• [#{msg.get('channel_name', '?')}] {msg.get('author_name', '?')}: "
        f"{msg.get('content', msg.get('text', ''))[:120]}"
        for msg in messages[:5]
    )
