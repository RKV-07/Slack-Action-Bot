from graph.workflow import sab_graph
from graph.state import ActionContext


def handle_sab_command(command: dict, client) -> str:
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    text = command.get("text", "")
    thread_ts = command.get("thread_ts")

    action_ctx = None
    thread_messages = []
    if thread_ts:
        try:
            msg_response = client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=100
            )
            messages = msg_response.get("messages", [])
            if messages:
                msg = messages[0]
                action_ctx = ActionContext(
                    user_id=user_id,
                    channel_id=channel_id,
                    message_ts=thread_ts,
                    original_message=msg.get("text", ""),
                    mentioned_by=msg.get("user", "unknown"),
                )
                thread_messages = [
                    {"user": m.get("user", "unknown"), "text": m.get("text", "")}
                    for m in messages
                    if not m.get("bot_id")
                ]
        except Exception as e:
            print(f"Error fetching thread context: {e}")

    initial_state = {
        "command_type": "unknown",
        "action_context": action_ctx,
        "reminder_data": None,
        "github_refs": [],
        "github_results": [],
        "user_id": user_id,
        "channel_id": channel_id,
        "message_ts": thread_ts or "",
        "raw_input": text if text else "",
        "response_message": "",
        "needs_llm": False,
        "llm_summary": None,
        "thread_messages": thread_messages,
        "max_messages": 10,
    }

    result = sab_graph.invoke(initial_state)
    return result.get("response_message", "Something went wrong.")
