import re
import atexit
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET
from handlers.commands import handle_sab_command
from handlers.events import handle_message_event, handle_app_mention
from services.reminder_service import shutdown_scheduler

app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
)

GITHUB_REF_PATTERN = re.compile(r"\b[\w-]+/[\w-]+#\d+\b")


@app.command("/sab")
def cmd_sab(ack, command, client, logger):
    ack()
    try:
        response = handle_sab_command(command, client)
        client.chat_postMessage(
            channel=command["channel_id"],
            text=response,
            thread_ts=command.get("thread_ts"),
        )
    except Exception as e:
        logger.error(f"Error handling /sab: {e}")
        client.chat_postMessage(
            channel=command["channel_id"],
            text="Something went wrong. Please try again.",
        )


@app.event("message")
def on_message(event, say, client, logger):
    if event.get("bot_id"):
        return
    text = event.get("text", "")
    if not GITHUB_REF_PATTERN.search(text):
        return
    handle_message_event(event, client, say)


@app.event("app_mention")
def on_mention(event, say, client, logger):
    handle_app_mention(event, client, say)


def start():
    atexit.register(shutdown_scheduler)
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    print("Starting Slack Advanced Actions Bot...")
    print("Features:")
    print("  - Summarize messages using local LLM (Qwen3-8B)")
    print("  - Set reminders with APS Scheduler")
    print("  - Fetch GitHub issues and PRs")
    print("  - Smart replies to mentions")
    handler.start()


if __name__ == "__main__":
    start()
