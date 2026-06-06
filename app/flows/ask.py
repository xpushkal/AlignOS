"""Ask-question flow (PRD §17.1, §9.1).

Searches confirmed memory + live evidence, verifies support, and produces a
grounded answer — or a no-evidence refusal when support is insufficient (§9.6).
"""
from __future__ import annotations

from typing import Any

from app import mcp_client


async def answer_question(
    question: str,
    workspace_id: str,
    channel_id: str | None = None,
    evidence_messages: list[str] | None = None,
) -> dict[str, Any]:
    """Return a grounded answer dict for a memory question."""
    search = await mcp_client.call_tool(
        "search_memory",
        {"query": question, "workspace_id": workspace_id, "channel_id": channel_id},
    )
    memory_items = search.get("memory_items", [])

    proposed = _draft_answer(memory_items)
    verdict = await mcp_client.call_tool(
        "verify_evidence",
        {
            "proposed_answer": proposed,
            "evidence_messages": evidence_messages or [],
            "memory_items": memory_items,
        },
    )

    support = verdict.get("support_level", "INSUFFICIENT_EVIDENCE")
    safe = verdict.get("safe_to_answer", False)
    confidence = verdict.get("final_confidence", verdict.get("confidence", 0.0))

    if not safe or support == "INSUFFICIENT_EVIDENCE":
        return {
            "answer": (
                "I could not find enough confirmed evidence to answer that. "
                "I found discussion but no confirmed decision."
            ),
            "support_level": support,
            "confidence": confidence,
            "source": "none",
            "refused": True,
            "memory_items": memory_items,
        }

    return {
        "answer": proposed,
        "support_level": support,
        "confidence": confidence,
        "source": "confirmed memory" if memory_items else "live discussion",
        "refused": False,
        "memory_items": memory_items,
    }


def _draft_answer(memory_items: list[dict]) -> str:
    if not memory_items:
        return ""
    top = memory_items[0]
    title = top.get("title", "").strip()
    summary = top.get("summary", "").strip()
    if summary and summary != title:
        return f"{title}. {summary}"
    return title or summary
