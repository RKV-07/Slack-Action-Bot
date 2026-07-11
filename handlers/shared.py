import re
import time
from graph.state import ActionContext
from slack_sdk.errors import SlackApiError

_bot_user_id: str = None
_bot_user_id_fetched: bool = False


def _call_with_backoff(fn, max_retries=1):
    """Call a Slack API function with retry on rate-limit."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except SlackApiError as e:
            if e.response.get("error") == "ratelimited" and attempt < max_retries:
                wait = int(e.response.headers.get("Retry-After", 5))
                print(f"[Shared] Rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            raise


def md_to_slack_mrkdwn(text: str) -> str:
    """Convert common Markdown to Slack mrkdwn before posting."""
    if not text:
        return text
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)      # **bold** -> *bold*
    text = re.sub(r'__(.+?)__', r'*\1*', text)           # __bold__ -> *bold*
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'<\2|\1>', text)  # [t](url) -> <url|t>
    # bare URLs (not already inside <...>) -> <url>
    text = re.sub(r'(?<!<)(https?://[^\s<>]+)', r'<\1>', text)
    return text


def _get_bot_user_id(client) -> str:
    """Return cached bot_user_id, fetching once via auth_test if needed."""
    global _bot_user_id, _bot_user_id_fetched
    if not _bot_user_id_fetched:
        try:
            auth_resp = client.auth_test()
            _bot_user_id = auth_resp.get("user_id")
        except Exception:
            _bot_user_id = None
        _bot_user_id_fetched = True
    return _bot_user_id


def is_real_message(msg: dict, bot_user_id: str = None) -> bool:
    """Shared filter: returns True if a Slack message is from a real human.

    Used by fetch_thread_messages, fetch_channel_messages, mcp_slack_server,
    and slack_summarize_service to keep filtering consistent.
    """
    if msg.get("bot_id"):
        return False
    if bot_user_id and msg.get("user") == bot_user_id:
        return False
    if msg.get("subtype") in ("bot_message", "bot_add"):
        return False
    if not msg.get("text", "").strip():
        return False
    return True


def fetch_thread_messages(client, channel_id: str, ts: str) -> tuple[str, list[dict]]:
    """Fetch messages from a thread (conversations_replies)."""
    try:
        resp = _call_with_backoff(lambda: client.conversations_replies(channel=channel_id, ts=ts, limit=100))

        # Check for API errors
        if not resp.get("ok"):
            error = resp.get("error", "unknown")
            print(f"[Shared] conversations_replies error: {error}")
            return "", []

        messages = resp.get("messages", [])
        if not messages:
            return "", []
        original = messages[0].get("text", "")

        bot_user_id = _get_bot_user_id(client)

        thread = []
        for m in messages:
            if not is_real_message(m, bot_user_id):
                continue
            thread.append({
                "user": m.get("user", "unknown"),
                "text": m.get("text", "")
            })

        return original, thread
    except SlackApiError:
        print("[Shared] Rate limited on conversations_replies — try again in a minute")
        return "", []
    except Exception as e:
        print(f"[Shared] Error fetching thread: {e}")
        return "", []


def fetch_channel_messages(client, channel_id: str, count: int = 25) -> list[dict]:
    """Fetch the last N human messages from a channel (not thread)."""
    try:
        # Over-fetch heavily — bot messages and short msgs get filtered out
        resp = _call_with_backoff(lambda: client.conversations_history(channel=channel_id, limit=count + 40))

        # Check for API errors
        if not resp.get("ok"):
            error = resp.get("error", "unknown")
            print(f"[Shared] conversations_history error: {error}")
            if error == "missing_scope":
                print("[Shared] Bot needs 'channels:history' scope. Add it in Slack App settings.")
            return []

        messages = resp.get("messages", [])
        if not messages:
            print(f"[Shared] No messages found in channel {channel_id}")
            return []

        bot_user_id = _get_bot_user_id(client)

        result = []
        for m in messages:
            if not is_real_message(m, bot_user_id):
                continue
            text = m.get("text", "").strip()
            if len(text) < 3:
                continue
            result.append({
                "user": m.get("user", "unknown"),
                "text": text
            })
            if len(result) >= count:
                break

        print(f"[Shared] Fetched {len(result)} channel messages from {channel_id}")

        result.reverse()  # normalize to oldest-first, matching fetch_thread_messages
        return result
    except SlackApiError:
        print("[Shared] Rate limited on conversations_history — try again in a minute")
        return []
    except Exception as e:
        print(f"[Shared] Error fetching channel messages: {e}")
        return []


def build_initial_state(
    user_id: str,
    channel_id: str,
    message_ts: str,
    raw_input: str,
    original_message: str = "",
    mentioned_by: str = None,
    thread_messages: list[dict] = None,
    action_token: str = "",
) -> dict:
    action_ctx = None
    if original_message:
        action_ctx = ActionContext(
            user_id=user_id,
            channel_id=channel_id,
            message_ts=message_ts,
            original_message=original_message,
            mentioned_by=mentioned_by,
        )

    return {
        "command_type": "help",
        "action_context": action_ctx,
        "reminder_data": None,
        "github_refs": [],
        "github_results": [],
        "user_id": user_id,
        "channel_id": channel_id,
        "message_ts": message_ts,
        "raw_input": raw_input,
        "response_message": "",
        "needs_llm": False,
        "llm_summary": None,
        "thread_messages": thread_messages or [],
        "max_messages": 25,
        # Learn command fields
        "learn_topic": "",
        "learn_resources": [],
        "learn_path": {},
        "learn_via_mcp": False,
        # Code review fields
        "review_pr_data": {},
        "review_security": "",
        "review_performance": "",
        "review_best_practices": "",
        "review_warning": "",
        "review_via_mcp": False,
        "review_semgrep_findings": [],
        # Real-time search
        "action_token": action_token or "",
        "search_query": "",
    }
