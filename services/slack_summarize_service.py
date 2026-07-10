"""
Slack Summarize Service - retrieve Slack messages via the Slack MCP server
(primary) or slack-sdk directly (fallback), enforce a context-message limit,
and summarize via the LLM.

When more messages are available than the configured limit, the user is warned
and only the most recent `max_messages` are summarized.
"""

import json

from config import SLACK_BOT_TOKEN, SLACK_SUMMARY_MAX_MESSAGES
from services.llm_service import summarize_thread_messages


def _fetch_via_mcp(channel_id: str, thread_ts: str = None) -> str:
    """Try the Slack MCP server. Returns raw JSON string or None."""
    try:
        from services.mcp_client import mcp_client

        if "slack" not in mcp_client._sessions:
            return None
        tool = "slack_get_thread_replies" if thread_ts else "slack_get_channel_history"
        args = {
            "channel_id": channel_id,
            "limit": SLACK_SUMMARY_MAX_MESSAGES + 1,  # +1 to detect overflow
        }
        if thread_ts:
            args["thread_ts"] = thread_ts
        result = mcp_client.call_tool("slack", tool, args)
        if result and isinstance(result, str) and not result.startswith("Error"):
            return result
    except Exception as e:
        print(f"[SlackSummarize] MCP fetch failed: {e}")
    return None


def _fetch_direct(channel_id: str, thread_ts: str = None) -> str:
    """Fallback: fetch directly with slack-sdk using the bot token."""
    if not SLACK_BOT_TOKEN:
        return None
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError

        client = WebClient(token=SLACK_BOT_TOKEN)
        if thread_ts:
            resp = client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=SLACK_SUMMARY_MAX_MESSAGES + 1
            )
        else:
            resp = client.conversations_history(
                channel=channel_id, limit=SLACK_SUMMARY_MAX_MESSAGES + 1
            )
        messages = [
            {"user": m.get("user", "unknown"), "text": m.get("text", ""), "ts": m.get("ts", "")}
            for m in resp.get("messages", [])
            if not m.get("bot_id") and m.get("text", "").strip()
        ]
        messages.reverse()
        return json.dumps({
            "messages": messages,
            "count": len(messages),
            "has_more": resp.get("has_more", False),
        })
    except SlackApiError as e:
        return json.dumps({"error": e.response.get("error", str(e))})
    except Exception as e:
        print(f"[SlackSummarize] Direct fetch failed: {e}")
        return None


def summarize_slack(channel_id: str, thread_ts: str = None) -> dict:
    """Fetch messages and produce a summary.

    Returns: {"summary": str, "warning": str, "error": str}
    """
    raw = _fetch_via_mcp(channel_id, thread_ts)
    if raw is None:
        raw = _fetch_direct(channel_id, thread_ts)

    if not raw:
        return {
            "summary": "",
            "warning": "",
            "error": (
                "Could not fetch messages. I need `channels:history` (and "
                "`groups:history` for private channels) scope. Ask a Slack admin "
                "to add it under OAuth & Permissions, then re-invite the bot."
            ),
        }

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"summary": "", "warning": "", "error": "Failed to parse Slack response."}

    if "error" in data:
        err = data["error"]
        hint = ""
        if err == "missing_scope":
            hint = " The bot is missing the required `channels:history` scope."
        return {"summary": "", "warning": "", "error": f"Slack error: {err}.{hint}"}

    messages = data.get("messages", [])
    has_more = data.get("has_more", False)

    warning = ""
    if has_more or len(messages) > SLACK_SUMMARY_MAX_MESSAGES:
        label = "thread" if thread_ts else "channel"
        warning = (
            f"⚠️ More than {SLACK_SUMMARY_MAX_MESSAGES} messages were found in this "
            f"{label}. Summarizing the most recent {SLACK_SUMMARY_MAX_MESSAGES} only."
        )
        messages = messages[-SLACK_SUMMARY_MAX_MESSAGES:]

    if not messages:
        return {"summary": "", "warning": "", "error": "No messages to summarize."}

    summary = summarize_thread_messages(messages, SLACK_SUMMARY_MAX_MESSAGES)
    return {"summary": summary, "warning": warning, "error": ""}
