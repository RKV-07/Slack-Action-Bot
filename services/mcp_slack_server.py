"""
Slack MCP Server - retrieves Slack messages over MCP (stdio transport).

Run as a subprocess by the bot's MCPClient. Uses the existing SLACK_BOT_TOKEN
via slack-sdk, so no extra credentials are required. Exposes tools that fetch
channel history and thread replies, returning chronological (oldest-first) JSON
with a `has_more` flag so callers can enforce a context-message limit.

Stdio transport is used so the bot connects the same way it connects to the
GitHub and Fetch MCP servers (see services/mcp_client.py).
"""

import json
import os

from mcp.server.fastmcp import FastMCP
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

mcp = FastMCP("slack-action-bot")


def _client() -> WebClient:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set in the environment.")
    return WebClient(token=token)


def _is_real_message(msg: dict) -> bool:
    """Match handlers/shared.py's is_real_message — must stay in sync."""
    if msg.get("bot_id"):
        return False
    if msg.get("subtype") in ("bot_message", "bot_add"):
        return False
    if not msg.get("text", "").strip():
        return False
    return True


def _clean(msg: dict) -> dict:
    return {
        "user": msg.get("user", "unknown"),
        "text": msg.get("text", ""),
        "ts": msg.get("ts", ""),
    }


def _collect(resp: dict, limit: int) -> dict:
    """Normalize a Slack API response into chronological MCP output.

    Over-fetches by +10 to buffer against bot/system messages being filtered
    out, matching shared.py's fetch_channel_messages approach.
    has_more reflects the raw Slack page; count reflects the filtered result.
    """
    messages = [_clean(m) for m in resp.get("messages", []) if _is_real_message(m)]
    messages.reverse()  # Slack returns newest-first; reverse to oldest-first
    # has_more is from Slack's raw page (before filtering); count is after
    # filtering — they may differ when bot messages were present.
    return {
        "messages": messages,
        "count": len(messages),
        "has_more": resp.get("has_more", False),
    }


@mcp.tool()
def slack_get_channel_history(channel_id: str, limit: int = 25) -> str:
    """Retrieve recent messages from a Slack channel.

    Args:
        channel_id: The channel ID (e.g. C0123ABCD).
        limit: Max messages to fetch. The server adds +10 internally to
               buffer against bot/system messages being filtered out.

    Returns JSON: {"messages": [...], "count": int, "has_more": bool}
    """
    try:
        client = _client()
        # Over-fetch to buffer against filtered bot messages
        resp = client.conversations_history(channel=channel_id, limit=limit + 10)
        return json.dumps(_collect(resp, limit))
    except SlackApiError as e:
        return json.dumps({"error": e.response.get("error", str(e))})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def slack_get_thread_replies(channel_id: str, thread_ts: str, limit: int = 25) -> str:
    """Retrieve replies in a Slack thread.

    Args:
        channel_id: The channel ID the thread lives in.
        thread_ts: The thread's parent message timestamp.
        limit: Max messages to fetch. The server adds +10 internally to
               buffer against bot/system messages being filtered out.

    Returns JSON: {"messages": [...], "count": int, "has_more": bool}
    """
    try:
        client = _client()
        # Over-fetch to buffer against filtered bot messages
        resp = client.conversations_replies(
            channel=channel_id, ts=thread_ts, limit=limit + 10
        )
        return json.dumps(_collect(resp, limit))
    except SlackApiError as e:
        return json.dumps({"error": e.response.get("error", str(e))})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run(transport="stdio")
