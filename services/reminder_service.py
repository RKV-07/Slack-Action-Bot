import uuid
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN

jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///reminders.db")}
scheduler = BackgroundScheduler(jobstores=jobstores)
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
            text=f"<@{user_id}> Reminder: {text}",
        )
    except Exception as e:
        print(f"[Reminder] Failed to send: {e}")


def schedule_reminder(user_id: str, text: str, delay_seconds: int, channel_id: str):
    _ensure_scheduler()
    run_date = datetime.now() + timedelta(seconds=delay_seconds)
    job_id = f"reminder_{uuid.uuid4().hex[:12]}"
    scheduler.add_job(
        _send_reminder,
        "date",
        run_date=run_date,
        args=[user_id, text, channel_id],
        id=job_id,
        replace_existing=False,
    )


def list_reminders(user_id: str) -> list[dict]:
    """List all pending reminders for a user."""
    _ensure_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        args = job.args or []
        if len(args) >= 3 and args[0] == user_id:
            run_time = job.next_run_time
            if run_time:
                jobs.append({
                    "id": job.id,
                    "text": args[1],
                    "run_time": run_time.strftime("%Y-%m-%d %H:%M UTC"),
                })
    return jobs


def cancel_reminder(job_id: str) -> bool:
    """Cancel a pending reminder by job ID."""
    _ensure_scheduler()
    try:
        scheduler.remove_job(job_id)
        return True
    except Exception:
        return False


def schedule_daily_digest(channel_id: str, hour: int = 9, minute: int = 0):
    """Schedule a daily GitHub digest for a channel."""
    _ensure_scheduler()
    scheduler.add_job(
        _post_daily_digest,
        "cron",
        hour=hour,
        minute=minute,
        args=[channel_id],
        id=f"digest_{channel_id}",
        replace_existing=True,
    )


def schedule_digest_demo(channel_id: str, delay_minutes: int = 2):
    """Schedule a one-shot digest for demo purposes."""
    _ensure_scheduler()
    run_date = datetime.now() + timedelta(minutes=delay_minutes)
    scheduler.add_job(
        _post_daily_digest,
        "date",
        run_date=run_date,
        args=[channel_id],
        id=f"digest_demo_{channel_id}",
        replace_existing=True,
    )


def cancel_daily_digest(channel_id: str) -> bool:
    """Cancel the daily digest for a channel."""
    _ensure_scheduler()
    try:
        scheduler.remove_job(f"digest_{channel_id}")
        return True
    except Exception:
        return False


def _post_daily_digest(channel_id: str):
    """Post daily digest of latest issues and PRs."""
    from services.github_service import fetch_latest_issues, fetch_latest_prs

    client = _get_client()
    issues = fetch_latest_issues(count=5)
    prs = fetch_latest_prs(count=5)

    lines = ["*📅 Daily Digest*", "", "*Issues:*"]
    lines += [f"• <{i['url']}|{i['title']}>" for i in issues] or ["  (none)"]
    lines += ["", "*PRs:*"]
    lines += [f"• <{p['url']}|{p['title']}>" for p in prs] or ["  (none)"]

    try:
        client.chat_postMessage(channel=channel_id, text="\n".join(lines))
    except Exception as e:
        print(f"[Digest] Failed to post: {e}")


def shutdown_scheduler():
    global _scheduler_started
    if _scheduler_started:
        scheduler.shutdown(wait=False)
        _scheduler_started = False
