import uuid
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN

scheduler = BackgroundScheduler()
_scheduler_started = False
_client = None


def _ensure_scheduler():
    global _scheduler_started
    if not _scheduler_started:
        scheduler.start()
        _scheduler_started = True


def _get_client() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=SLACK_BOT_TOKEN)
    return _client


def _send_reminder(user_id: str, text: str, channel_id: str):
    client = _get_client()
    try:
        client.chat_postMessage(
            channel=channel_id,
            text=f"Reminder: {text}",
        )
    except Exception as e:
        print(f"Failed to send reminder: {e}")


def schedule_reminder(user_id: str, text: str, delay_seconds: int, channel_id: str = None):
    _ensure_scheduler()
    target_channel = channel_id or user_id
    run_date = datetime.now() + timedelta(seconds=delay_seconds)
    scheduler.add_job(
        _send_reminder,
        "date",
        run_date=run_date,
        args=[user_id, text, target_channel],
        id=f"reminder_{user_id}_{uuid.uuid4().hex[:8]}",
        replace_existing=False,
    )


def shutdown_scheduler():
    global _scheduler_started
    if _scheduler_started:
        scheduler.shutdown(wait=False)
        _scheduler_started = False
