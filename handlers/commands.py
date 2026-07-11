import concurrent.futures
import re
from config import SLACK_SUMMARY_MAX_MESSAGES
from graph.workflow import sab_graph
from handlers.shared import fetch_thread_messages, fetch_channel_messages, build_initial_state, md_to_slack_mrkdwn

# Limit concurrent background threads to prevent resource exhaustion
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)


def _execute_command_graph_async(state: dict, client, command: dict):
    try:
        result = sab_graph.invoke(state)
        client.chat_postMessage(
            channel=command["channel_id"],
            text=md_to_slack_mrkdwn(result.get("response_message", "Something went wrong.")),
            thread_ts=command.get("thread_ts"),
        )
    except Exception as e:
        import traceback
        print(f"[Command Error] Failed background execution: {e}")
        traceback.print_exc()
        try:
            client.chat_postMessage(
                channel=command["channel_id"],
                text="Sorry, I ran into an error processing that request.",
                thread_ts=command.get("thread_ts"),
            )
        except Exception:
            pass


def handle_sab_command(command: dict, client) -> str:
    user_id = command["user_id"]
    channel_id = command["channel_id"]
    text = command.get("text", "")
    thread_ts = command.get("thread_ts")

    original_msg = ""
    thread_messages = []
    mentioned_by = None

    if thread_ts:
        original_msg, thread_messages = fetch_thread_messages(client, channel_id, thread_ts)
        if thread_messages:
            mentioned_by = thread_messages[0].get("user")

    # If no thread messages and command looks like summarize, fetch channel context
    raw_lower = (text or "").lower().strip()
    if not thread_messages and re.search(r'\bsum+ar\w*\b|\bsum+ra\w*\b', raw_lower):
        thread_messages = fetch_channel_messages(client, channel_id, count=SLACK_SUMMARY_MAX_MESSAGES)

    state = build_initial_state(
        user_id=user_id,
        channel_id=channel_id,
        message_ts=thread_ts or "",
        raw_input=text or "",
        original_message=original_msg,
        mentioned_by=mentioned_by,
        thread_messages=thread_messages,
    )

    # Submit to thread pool with max workers limit
    _executor.submit(_execute_command_graph_async, state, client, command)

    # Return an immediate acknowledgment message back to main.py
    return "Processing your request... :hourglass_flowing_sand:"
