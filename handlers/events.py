from graph.workflow import sab_graph
from services.github_service import detect_github_refs, fetch_github_issue


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


def handle_app_mention(event: dict, client, say):
    from graph.state import ActionContext

    user_id = event["user"]
    channel_id = event["channel"]

    try:
        msg_response = client.conversations_replies(
            channel=channel_id, ts=event["ts"], limit=1
        )
        messages = msg_response.get("messages", [])
        original_msg = messages[0]["text"] if messages else "No message context available"

        initial_state = {
            "command_type": "unknown",
            "action_context": ActionContext(
                user_id=user_id,
                channel_id=channel_id,
                message_ts=event["ts"],
                original_message=original_msg,
                mentioned_by=user_id,
            ),
            "reminder_data": None,
            "github_refs": [],
            "github_results": [],
            "user_id": user_id,
            "channel_id": channel_id,
            "message_ts": event["ts"],
            "raw_input": original_msg,
            "response_message": "",
            "needs_llm": False,
            "llm_summary": None,
        }

        result = sab_graph.invoke(initial_state)
        say(result.get("response_message", "Hey! You were mentioned."))
    except Exception as e:
        print(f"Error in handle_app_mention: {e}")
        say(f"Hi <@{user_id}>! You were mentioned. Use `/sab` to handle this.")
