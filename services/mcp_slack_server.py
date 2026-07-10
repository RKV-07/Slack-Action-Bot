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


def _clean(msg: dict) -> dict:
    return {
        "user": msg.get("user", "unknown"),
        "text": msg.get("text", ""),
        "ts": msg.get("ts", ""),
    }


def _collect(resp: dict) -> dict:
    """Normalize a Slack API response into chronological MCP output."""
    messages = [
        _clean(m)
        for m in resp.get("messages", [])
        if not m.get("bot_id") and m.get("text", "").strip()
    ]
    # Slack returns newest-first; reverse to oldest-first for summarization.
    messages.reverse()
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
        limit: Max messages to fetch (use 26 to detect >25).

    Returns JSON: {"messages": [...], "count": int, "has_more": bool}
    """
    try:
        client = _client()
        resp = client.conversations_history(channel=channel_id, limit=limit)
        return json.dumps(_collect(resp))
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
        limit: Max messages to fetch (use 26 to detect >25).

    Returns JSON: {"messages": [...], "count": int, "has_more": bool}
    """
    try:
        client = _client()
        resp = client.conversations_replies(
            channel=channel_id, ts=thread_ts, limit=limit
        )
        return json.dumps(_collect(resp))
    except SlackApiError as e:
        return json.dumps({"error": e.response.get("error", str(e))})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run(transport="stdio")
