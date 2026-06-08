"""Meeting-to-Execution Pipeline flow (Feature 5).

Converts a thread discussion into a structured list of tasks, decisions, and blockers, and saves them on command.
"""
from __future__ import annotations

from typing import Any
from app import mcp_client
from app.llm import get_llm_client
from app.concurrency import run_blocking


async def generate_plan(discussion_text: str) -> dict[str, Any]:
    """Analyze chat context and return proposed summary, tasks, decisions, and blockers."""
    client = get_llm_client()
    return await run_blocking(client.extract_meeting_execution, discussion_text)


async def persist_plan(
    plan: dict[str, Any], workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    """Persist all decisions, tasks, and blockers in the execution plan to DB."""
    from app.db import get_repository
    repo = get_repository()

    saved_decisions = []
    saved_tasks = []
    saved_blockers = []

    # 1. Decisions
    for dec in plan.get("decisions", []):
        row = await run_blocking(
            repo.save_decision,
            {
                "workspace_id": workspace_id,
                "channel_id": channel_id,
                "title": dec.get("title", ""),
                "summary": dec.get("title", ""),
                "reason": dec.get("reason", ""),
                "status": "confirmed",
                "confidence": 0.9,
            },
        )
        saved_decisions.append(row)

    # 2. Tasks & Deadlines
    for task in plan.get("action_items", []):
        row = await run_blocking(
            repo.save_task,
            {
                "workspace_id": workspace_id,
                "channel_id": channel_id,
                "title": task.get("title", ""),
                "owner_user_id": task.get("owner"),
                "status": "open",
                "due_date": task.get("deadline"),
            },
        )
        saved_tasks.append(row)

    # 3. Blockers
    for blocker in plan.get("blockers", []):
        row = await run_blocking(
            repo.save_blocker,
            {
                "workspace_id": workspace_id,
                "channel_id": channel_id,
                "title": blocker.get("title", ""),
                "description": blocker.get("description", ""),
                "status": "open",
            },
        )
        saved_blockers.append(row)

    return {
        "decisions": saved_decisions,
        "tasks": saved_tasks,
        "blockers": saved_blockers,
    }
