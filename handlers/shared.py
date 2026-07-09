from graph.state import ActionContext


def fetch_thread_messages(client, channel_id: str, ts: str) -> tuple[str, list[dict]]:
    try:
        resp = client.conversations_replies(channel=channel_id, ts=ts, limit=100)
        messages = resp.get("messages", [])
        if not messages:
            return "", []
        original = messages[0].get("text", "")
        thread = [
            {"user": m.get("user", "unknown"), "text": m.get("text", "")}
            for m in messages
            if not m.get("bot_id")
        ]
        return original, thread
    except Exception as e:
        print(f"[Shared] Error fetching thread: {e}")
        return "", []


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
        "max_messages": 10,
    }
