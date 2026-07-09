import threading
import re
from graph.workflow import sab_graph
from services.github_service import detect_github_refs, fetch_github_issue
from handlers.shared import fetch_thread_messages, build_initial_state


def handle_message_event(event: dict, client, say) -> bool:
    text = event.get("text", "")
    refs = detect_github_refs(text)

    if not refs:
        return False

    responses = []
    for ref in refs:
        parts = ref.split("#")
        if len(parts) != 2:
            continue
        repo = parts[0]
        try:
            num = int(parts[1])
        except ValueError:
            continue
        issue = fetch_github_issue(repo, num)
        if issue:
            status = "Open" if issue["state"] == "open" else "Closed"
            responses.append(
                f"*{issue['title']}*\nStatus: {status}\n<{issue['url']}|View on GitHub>"
            )

    if responses:
        say(text="\n\n".join(responses))
        return True
    return False


def _execute_graph_async(state: dict, say):
    try:
        # Run the local Llama pipeline safely in a separate thread
        result = sab_graph.invoke(state)
        say(text=result.get("response_message", "Hey! How can I help you?"))
    except Exception as e:
        print(f"[Graph Error] Failed background execution: {e}")
        say(text="Sorry, I ran into an error processing that request.")


def handle_app_mention(event: dict, client, say):
    # Check if this is a Slack retry to drop duplicate requests immediately
    if event.get("headers", {}).get("X-Slack-Retry-Num"):
        return

    user_id = event["user"]
    channel_id = event["channel"]
    raw_text = event.get("text", "")
    clean_msg = re.sub(r'<@[A-Za-z0-9]+>', '', raw_text).strip()

    original_msg, thread_messages = fetch_thread_messages(client, channel_id, event["ts"])

    state = build_initial_state(
        user_id=user_id,
        channel_id=channel_id,
        message_ts=event["ts"],
        raw_input=clean_msg,
        original_message=original_msg or raw_text,
        mentioned_by=user_id,
        thread_messages=thread_messages,
    )

    # Spin off graph invocation to a background thread so the event loop can finish within 3s
    thread = threading.Thread(target=_execute_graph_async, args=(state, say))
    thread.start()
