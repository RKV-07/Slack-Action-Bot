import re
import atexit
import threading
from collections import OrderedDict
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET, GITHUB_TOKEN, MCP_GITHUB_ENABLED, MCP_FETCH_ENABLED, MCP_SLACK_ENABLED
from slack_sdk.errors import SlackApiError
from handlers.commands import handle_sab_command
from handlers.events import handle_message_event, handle_app_mention
from services.reminder_service import shutdown_scheduler
from services.slack_features import with_processing_reaction

app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
)

GITHUB_REF_PATTERN = re.compile(r"\b[\w-]+/[\w-]+#\d+\b")

_seen = OrderedDict()


def _already_processed(key: str) -> bool:
    if key in _seen:
        return True
    _seen[key] = True
    if len(_seen) > 200:
        _seen.popitem(last=False)
    return False


def init_mcp_servers():
    """Initialize MCP server connections on startup."""
    try:
        from services.mcp_client import setup_mcp_servers
        setup_mcp_servers(github_token=GITHUB_TOKEN)
        print("[MCP] Server initialization complete")
    except Exception as e:
        print(f"[MCP] Failed to initialize servers: {e}")
        print("[MCP] Learn and CodeReview commands may have limited functionality")


def _cleanup_mcp():
    """Shutdown MCP client on exit."""
    try:
        from services.mcp_client import mcp_client
        for name in list(mcp_client._sessions.keys()):
            try:
                mcp_client.disconnect(name)
            except Exception:
                pass
        print("[MCP] Cleanup complete")
    except Exception:
        pass


@app.command("/sab")
def cmd_sab(ack, command, client, logger):
    ack()
    if _already_processed(command.get("trigger_id", "")):
        return
    channel_id = command["channel_id"]
    user_id = command["user_id"]
    thread_ts = command.get("thread_ts")
    response = None
    try:
        response = handle_sab_command(command, client)
        client.chat_postMessage(
            channel=channel_id,
            text=response,
            thread_ts=thread_ts,
        )
    except SlackApiError as e:
        if e.response.get("error") == "not_in_channel":
            logger.warning(f"Bot not in channel {channel_id}, sending DM to {user_id}")
            try:
                client.chat_postMessage(
                    channel=user_id,
                    text=f"I'm not in that channel yet. Here's your response:\n\n{response or 'Processing your request...'}",
                )
            except Exception:
                pass
        else:
            logger.error(f"Error handling /sab: {e}")
    except Exception as e:
        logger.error(f"Error handling /sab: {e}")


@app.event("message")
@with_processing_reaction
def on_message(event, say, client, logger):
    if event.get("bot_id"):
        return
    # Dedup: Socket Mode can redeliver events
    event_ts = event.get("ts", "")
    if event_ts and _already_processed(f"msg_{event_ts}"):
        return
    text = event.get("text", "")
    if not GITHUB_REF_PATTERN.search(text):
        return
    # Skip if bot is mentioned (app_mention handler will process it)
    if re.search(r'<@[A-Za-z0-9]+>', text):
        return
    try:
        handle_message_event(event, client, say)
    except Exception as e:
        logger.error(f"Error in message handler: {e}")
        say("Something went wrong while fetching GitHub data.")


@app.event("app_mention")
@with_processing_reaction
def on_mention(event, say, client, logger, context):
    # Dedup: Socket Mode can redeliver events
    event_ts = event.get("ts", "")
    if event_ts and _already_processed(f"mention_{event_ts}"):
        return
    try:
        handle_app_mention(event, client, say, context=context)
    except Exception as e:
        logger.error(f"Error in mention handler: {e}")
        say("Something went wrong. Try `/sab test` to check LLM.")


def start():
    atexit.register(shutdown_scheduler)
    atexit.register(_cleanup_mcp)
    # Check LLM context size at boot — fails loud instead of silent 400s later
    try:
        from services.llm_service import check_llm_context_size
        check_llm_context_size()
    except Exception as e:
        print(f"[LLM] Context size check failed: {e}")
    # Initialize MCP servers in background thread so bot boots immediately
    if MCP_GITHUB_ENABLED or MCP_FETCH_ENABLED or MCP_SLACK_ENABLED:
        t = threading.Thread(target=init_mcp_servers, daemon=True)
        t.start()
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    print("Starting Slack Advanced Actions Bot...")
    handler.start()


if __name__ == "__main__":
    start()
