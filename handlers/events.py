import threading
import re
from graph.workflow import sab_graph
from services.github_service import detect_github_refs, fetch_github_issue
from handlers.shared import fetch_thread_messages, fetch_channel_messages, build_initial_state


def _execute_message_github_async(refs: list, say):
    """Fetch GitHub refs in background to avoid blocking event loop."""
    try:
        responses = []
        for ref in refs:
            if "#" not in ref:
                continue
            parts = ref.split("#")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                continue
            repo = parts[0]
            try:
                num = int(parts[1])
            except ValueError:
                continue
            print(f"[GitHub] Fetching {repo}#{num}...")
            issue = fetch_github_issue(repo, num)
            if issue:
                status = "Open" if issue["state"] == "open" else "Closed"
                responses.append(
                    f"*{issue['title']}*\nStatus: {status}\n<{issue['url']}|View on GitHub>"
                )
            else:
                print(f"[GitHub] Could not fetch {repo}#{num}")

        if responses:
            say(text="\n\n".join(responses))
        else:
            say(text="Could not fetch GitHub issue/PR details.")
    except Exception as e:
        import traceback
        print(f"[Message Error] Failed GitHub fetch: {e}")
        traceback.print_exc()
        say(text="Sorry, I ran into an error fetching GitHub data.")


def handle_message_event(event: dict, client, say) -> bool:
    text = event.get("text", "")
    refs = detect_github_refs(text)

    if not refs:
        return False

    thread = threading.Thread(target=_execute_message_github_async, args=(refs, say))
    thread.start()
    return True


def _execute_graph_async(state: dict, say):
    try:
        print(f"[Graph] Running with command_type={state.get('command_type')}, "
              f"thread_messages={len(state.get('thread_messages', []))} msgs")
        result = sab_graph.invoke(state)
        response = result.get("response_message", "Hey! How can I help you?")
        print(f"[Graph] Response: {response[:100]}...")
        say(text=response)
    except Exception as e:
        import traceback
        print(f"[Graph Error] Failed background execution: {e}")
        traceback.print_exc()
        say(text="Sorry, I ran into an error processing that request.")


def handle_app_mention(event: dict, client, say, context: dict = None):
    # Bolt injects retry_num in context, not in event headers
    if context and context.get("retry_num"):
        return

    user_id = event["user"]
    channel_id = event["channel"]
    raw_text = event.get("text", "")
    clean_msg = re.sub(r'<@[A-Za-z0-9]+>', '', raw_text).strip()

    print(f"[Mention] user={user_id}, channel={channel_id}, raw='{clean_msg}'")

    # Try thread first
    original_msg, thread_messages = fetch_thread_messages(client, channel_id, event["ts"])
    print(f"[Mention] Thread messages: {len(thread_messages)}")

    # If no thread, fetch last 6 channel messages
    if not thread_messages:
        thread_messages = fetch_channel_messages(client, channel_id, count=6)
        print(f"[Mention] Channel messages: {len(thread_messages)}")

    state = build_initial_state(
        user_id=user_id,
        channel_id=channel_id,
        message_ts=event["ts"],
        raw_input=clean_msg,
        original_message=original_msg or raw_text,
        mentioned_by=user_id,
        thread_messages=thread_messages,
    )

    thread = threading.Thread(target=_execute_graph_async, args=(state, say))
    thread.start()
