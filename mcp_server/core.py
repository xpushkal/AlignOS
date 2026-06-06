"""Pure implementations of the 8 AlignOS MCP tools.

Each function takes/returns plain JSON-serializable values and matches the I/O
contracts in Docs/MCP_TOOLS.md §2. They depend only on the repository and the LLM
client, so they can be invoked either over the MCP transport (mcp_server.server)
or directly as a local fallback (app.mcp_client).
"""
from __future__ import annotations

from typing import Any

from app.db import get_repository
from app.llm import get_llm_client

TOOL_NAMES = [
    "detect_decision",
    "save_decision",
    "search_memory",
    "detect_conflict",
    "verify_evidence",
    "generate_project_summary",
    "reopen_decision",
    "log_conflict_action",
]


def detect_decision(
    message: str, thread_context: str = "", recent_channel_context: str = ""
) -> dict[str, Any]:
    result = get_llm_client().detect_decision(
        message, thread_context, recent_channel_context
    )
    result.setdefault("evidence_ids", [])
    return result


def save_decision(
    decision: dict[str, Any],
    workspace_id: str,
    channel_id: str | None = None,
    confirmed_by: str | None = None,
) -> dict[str, Any]:
    repo = get_repository()
    row = repo.save_decision(
        {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "title": decision.get("title", ""),
            "summary": decision.get("summary", ""),
            "reason": decision.get("reason", ""),
            "confidence": decision.get("confidence"),
            "thread_ts": decision.get("thread_ts"),
            "status": "confirmed",
        }
    )
    evidence = decision.get("evidence", []) or []
    if evidence:
        repo.add_evidence(row["id"], evidence)
    return {"decision_id": row["id"], "status": row["status"]}


def search_memory(
    query: str, workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    items = get_repository().search_memory(query, workspace_id, channel_id)
    return {"memory_items": items}


def detect_conflict(
    new_message: str,
    relevant_memory: list[dict] | None = None,
    recent_context: str = "",
) -> dict[str, Any]:
    return get_llm_client().detect_conflict(
        new_message, relevant_memory or [], recent_context
    )


def verify_evidence(
    proposed_answer: str,
    evidence_messages: list[str] | None = None,
    memory_items: list[dict] | None = None,
) -> dict[str, Any]:
    return get_llm_client().verify_evidence(
        proposed_answer, evidence_messages or [], memory_items or []
    )


def generate_project_summary(
    workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    items = get_repository().list_memory(workspace_id, channel_id)
    buckets: dict[str, list[dict]] = {
        "decisions": [],
        "tasks": [],
        "blockers": [],
        "deadlines": [],
        "questions": [],
        "summaries": [],
    }
    plural = {
        "decision": "decisions",
        "task": "tasks",
        "blocker": "blockers",
        "deadline": "deadlines",
        "question": "questions",
        "summary": "summaries",
    }
    for item in items:
        key = plural.get(item.get("type", ""), None)
        if key:
            buckets[key].append(item)
    confirmed = [d for d in buckets["decisions"] if d.get("status") == "confirmed"]
    return {
        "workspace_id": workspace_id,
        "channel_id": channel_id,
        "confirmed_decisions": confirmed,
        "open_tasks": [t for t in buckets["tasks"] if t.get("status") != "done"],
        "blockers": buckets["blockers"],
        "unresolved_questions": buckets["questions"],
        "deadlines": buckets["deadlines"],
    }


def reopen_decision(
    decision_id: str, workspace_id: str, requested_by: str | None = None
) -> dict[str, Any]:
    row = get_repository().update_decision_status(decision_id, "reopened")
    if not row:
        return {"decision_id": decision_id, "status": "not_found"}
    return {"decision_id": row["id"], "status": row["status"]}


def log_conflict_action(
    conflict_id: str, action: str, actor_user_id: str | None = None
) -> dict[str, Any]:
    status_map = {
        "remind": "open",
        "reopen": "reopened_decision",
        "ignore": "ignored",
        "resolve": "resolved",
    }
    status = status_map.get(action, "open")
    row = get_repository().update_conflict_status(conflict_id, status)
    if not row:
        return {"conflict_id": conflict_id, "status": "not_found"}
    return {"conflict_id": row["id"], "status": row["status"]}


# Dispatch table used by both the MCP server and the local fallback client.
DISPATCH = {
    "detect_decision": detect_decision,
    "save_decision": save_decision,
    "search_memory": search_memory,
    "detect_conflict": detect_conflict,
    "verify_evidence": verify_evidence,
    "generate_project_summary": generate_project_summary,
    "reopen_decision": reopen_decision,
    "log_conflict_action": log_conflict_action,
}


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in DISPATCH:
        raise KeyError(f"Unknown tool: {name}")
    return DISPATCH[name](**arguments)
