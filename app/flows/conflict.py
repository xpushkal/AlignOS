"""Conflict-detection flow (PRD §17.3, §9.4).

Finds memory related to a new message, compares for contradiction, and (when a
conflict is found) persists it so the Slack layer can render an alert card with
Remind / Reopen / Ignore actions.
"""
from __future__ import annotations

from typing import Any

from app import mcp_client
from app.llm import heuristics


async def check_conflict(
    message: str,
    workspace_id: str,
    channel_id: str | None = None,
    message_ts: str | None = None,
    recent_context: str = "",
) -> dict[str, Any]:
    """Return {conflict: bool, detection: {...}, conflict_id?: str}.

    Cheap pre-gate: only escalate to the LLM when the message either shares
    keywords with confirmed memory (direct overlap) or trips the rule-based
    conflict signal (e.g. opposing tech terms). Unrelated chatter skips the LLM.
    """
    from app.db import get_repository

    search = await mcp_client.call_tool(
        "search_memory",
        {"query": message, "workspace_id": workspace_id, "channel_id": channel_id},
    )
    relevant = search.get("memory_items", [])
    if not relevant:
        # No keyword overlap. A contradiction can still use different words than
        # the memory it conflicts with (e.g. "MongoDB" vs a stored "PostgreSQL"
        # decision), so consult recent memory — but only pay for the LLM if the
        # cheap rule-based signal fires (PRD §17.3 step 5).
        recent = get_repository().list_memory(workspace_id, channel_id)
        if not heuristics.has_conflict_signal(message, recent):
            return {"conflict": False, "detection": {"is_conflict": False}}
        relevant = recent

    detection = await mcp_client.call_tool(
        "detect_conflict",
        {
            "new_message": message,
            "relevant_memory": relevant,
            "recent_context": recent_context,
        },
    )
    if not detection.get("is_conflict"):
        return {"conflict": False, "detection": detection}

    # Persist the conflict through the repository (no dedicated MCP tool needed).
    row = get_repository().save_conflict(
        {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "message_ts": message_ts,
            "conflict_type": detection.get("conflict_type"),
            "severity": detection.get("severity"),
            "new_message_summary": message,
            "conflicting_memory_id": detection.get("conflicting_memory_id"),
            "explanation": detection.get("explanation"),
        }
    )
    return {"conflict": True, "detection": detection, "conflict_id": row["id"]}
