"""Decision-detection flow (PRD §17.2, §9.2).

Runs detection on a message + context. If a decision is detected with enough
confidence, returns a proposal the Slack layer renders as a confirmation card.
Saving happens later on Confirm (see app.flows.decision.confirm_decision).
"""
from __future__ import annotations

from typing import Any

from app import mcp_client
from app.llm import heuristics

# Below this confidence we stay silent rather than nagging on brainstorming.
MIN_CONFIDENCE = 0.6


async def detect_and_propose(
    message: str,
    workspace_id: str,
    channel_id: str | None = None,
    thread_context: str = "",
    recent_channel_context: str = "",
) -> dict[str, Any]:
    """Detect a decision; return {proposed: bool, decision: {...}}.

    Cheap pre-gate: skip the LLM entirely unless the message contains decision
    language. This avoids an LLM call on the majority of channel chatter.
    """
    if not heuristics.has_decision_cue(message):
        return {"proposed": False, "decision": {"is_decision": False, "confidence": 0.0}}

    result = await mcp_client.call_tool(
        "detect_decision",
        {
            "message": message,
            "thread_context": thread_context,
            "recent_channel_context": recent_channel_context,
        },
    )
    is_decision = result.get("is_decision", False)
    confidence = result.get("confidence", 0.0)
    proposed = bool(is_decision and confidence >= MIN_CONFIDENCE)
    return {"proposed": proposed, "decision": result}


async def confirm_decision(
    decision: dict[str, Any],
    workspace_id: str,
    channel_id: str | None = None,
    confirmed_by: str | None = None,
) -> dict[str, Any]:
    """Persist a confirmed decision; returns {decision_id, status}."""
    return await mcp_client.call_tool(
        "save_decision",
        {
            "decision": decision,
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "confirmed_by": confirmed_by,
        },
    )
