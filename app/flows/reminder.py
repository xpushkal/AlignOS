"""Personal Deadline Reminder flow (Feature 9).

Extracts reminders from conversations, saves them to the DB, and runs a background loop to send DMs.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any
from app.llm import get_llm_client
from app.concurrency import run_blocking

logger = logging.getLogger("alignos.reminders")


async def detect_reminder(message: str) -> dict[str, Any]:
    """Analyze message to see if a task reminder can be extracted."""
    client = get_llm_client()
    return await run_blocking(client.extract_reminder, message)


async def schedule_reminder(
    workspace_id: str,
    task_title: str,
    owner_slack_id: str,
    deadline: str | None = None,
    remind_at: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Persist a scheduled reminder in the database."""
    from app.db import get_repository
    repo = get_repository()

    # Parse remind_at date
    if remind_at:
        try:
            # Ensure remind_at is parsed correctly (ISO)
            remind_time = datetime.datetime.fromisoformat(remind_at.replace("Z", "+00:00"))
        except Exception:
            remind_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10)
    else:
        remind_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10)

    row = await run_blocking(
        repo.save_reminder,
        {
            "workspace_id": workspace_id,
            "task_id": task_id,
            "owner_slack_id": owner_slack_id,
            "task_title": task_title,
            "deadline": deadline,
            "remind_at": remind_time,
            "status": "scheduled",
        },
    )
    return row


async def check_reminders_and_send(slack_client: Any) -> int:
    """Scan the database for pending reminders and DM the task owners."""
    from app.db import get_repository
    repo = get_repository()

    pending = await run_blocking(repo.get_pending_reminders)
    sent_count = 0

    for rem in pending:
        rid = rem["id"]
        owner = rem["owner_slack_id"]
        title = rem["task_title"]
        due = rem.get("deadline") or "soon"

        # Owner slack id might be '<@U123456>' or a username, clean it
        user_id = owner.strip("<@>")
        
        msg = f":alarm_clock: *Deadline Reminder*: Your task *'{title}'* is due *{due}*."
        
        try:
            # Open DM channel and post message
            await run_blocking(
                slack_client.chat_postMessage,
                channel=user_id,
                text=msg,
            )
            # Update status to sent
            await run_blocking(repo.update_reminder_status, rid, "sent")
            sent_count += 1
        except Exception as exc:
            logger.exception("Failed to send reminder DM to user %s: %s", user_id, exc)
            # Mark failed/retry later? Keep scheduled or mark error to prevent crash loop
            await run_blocking(repo.update_reminder_status, rid, "failed")

    return sent_count
