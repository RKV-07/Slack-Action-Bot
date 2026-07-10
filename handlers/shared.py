from graph.state import ActionContext

_bot_user_id: str = None
_bot_user_id_fetched: bool = False


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


def fetch_thread_messages(client, channel_id: str, ts: str) -> tuple[str, list[dict]]:
    """Fetch messages from a thread (conversations_replies)."""
    try:
        resp = client.conversations_replies(channel=channel_id, ts=ts, limit=100)

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
            if m.get("bot_id"):
                continue
            if bot_user_id and m.get("user") == bot_user_id:
                continue
            if m.get("subtype") in ("bot_message", "bot_add"):
                continue
            thread.append({
                "user": m.get("user", "unknown"),
                "text": m.get("text", "")
            })

        return original, thread
    except Exception as e:
        print(f"[Shared] Error fetching thread: {e}")
        return "", []


def fetch_channel_messages(client, channel_id: str, count: int = 6) -> list[dict]:
    """Fetch the last N messages from a channel (not thread)."""
    try:
        resp = client.conversations_history(channel=channel_id, limit=count + 10)

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
            if m.get("bot_id"):
                continue
            if bot_user_id and m.get("user") == bot_user_id:
                continue
            if m.get("subtype") in ("bot_message", "bot_add"):
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
        return result
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
        # Code review fields
        "review_pr_data": {},
        "review_security": "",
        "review_performance": "",
        "review_best_practices": "",
    }
