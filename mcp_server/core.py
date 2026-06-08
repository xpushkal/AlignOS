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
    "get_decision_timeline",
    "get_cleanup_suggestions",
    "execute_cleanup_action",
    "generate_prd_suggestions",
    "get_project_health",
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
            "confirmed_by_user_id": confirmed_by,
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


def generate_answer(
    question: str,
    memory_items: list[dict] | None = None,
    evidence_messages: list[str] | None = None,
) -> dict[str, Any]:
    return get_llm_client().generate_answer(
        question, memory_items or [], evidence_messages or []
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


def get_decision_timeline(
    workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    repo = get_repository()
    decisions = repo.list_decisions(workspace_id, channel_id)
    confirmed = [d for d in decisions if d.get("status") == "confirmed"]
    # Attach evidence if any exists
    for dec in confirmed:
        dec["evidence"] = repo.get_evidence(dec["id"])
    return {"timeline": confirmed}


def get_cleanup_suggestions(
    workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    repo = get_repository()
    items = repo.list_memory(workspace_id, channel_id)
    decisions = repo.list_decisions(workspace_id, channel_id)
    
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    
    stale_decisions = []
    for dec in decisions:
        if dec.get("status") == "confirmed":
            created_at_str = dec.get("created_at")
            if created_at_str:
                try:
                    if isinstance(created_at_str, str):
                        created_at = datetime.datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    else:
                        created_at = created_at_str
                    if (now - created_at).days > 30:
                        stale_decisions.append(dec)
                except Exception:
                    pass

    # Duplicate tasks
    tasks = [item for item in items if item.get("type") == "task"]
    duplicate_tasks = []
    grouped_tasks: dict[str, list[dict]] = {}
    for task in tasks:
        norm_title = "".join(c for c in task.get("title", "").lower() if c.isalnum())
        grouped_tasks.setdefault(norm_title, []).append(task)
    for t_list in grouped_tasks.values():
        if len(t_list) > 1:
            duplicate_tasks.append(t_list)

    # Outdated/superseded decisions
    outdated_decisions = [dec for dec in decisions if dec.get("status") in ("superseded", "reopened")]

    # Completed tasks older than 14 days
    completed_tasks = []
    for item in items:
        if item.get("type") == "task" and item.get("status") == "done":
            updated_str = item.get("updated_at")
            if updated_str:
                try:
                    if isinstance(updated_str, str):
                        updated_at = datetime.datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                    else:
                        updated_at = updated_str
                    if (now - updated_at).days > 14:
                        completed_tasks.append(item)
                except Exception:
                    pass

    # Low confidence or rejected memory items
    low_confidence = []
    for item in items:
        conf = item.get("confidence")
        if conf is not None:
            try:
                if float(conf) < 0.5:
                    low_confidence.append(item)
            except Exception:
                pass
        if item.get("status") == "rejected":
            low_confidence.append(item)

    return {
        "stale_decisions": stale_decisions,
        "duplicate_tasks": duplicate_tasks,
        "outdated_decisions": outdated_decisions,
        "completed_tasks": completed_tasks,
        "low_confidence": low_confidence,
    }


def execute_cleanup_action(
    action: str, item_id: str, target_id: str | None = None
) -> dict[str, Any]:
    repo = get_repository()
    result = repo.execute_cleanup_action(action, item_id, target_id)
    return {"status": "success", "result": result}


def generate_prd_suggestions(decision_id: str, workspace_id: str) -> dict[str, Any]:
    repo = get_repository()
    decision = repo.get_decision(decision_id)
    if not decision:
        return {"suggestions": []}

    title = decision.get("title", "")
    summary = decision.get("summary", "")
    reason = decision.get("reason", "")

    client = get_llm_client()
    if client.mode == "openrouter":
        prompt = (
            "Analyze the following team decision and generate suggested PRD (Product Requirements Document) "
            "changes. Propose standard sections (e.g. Scope, Features, Roadmap, Security) to update, "
            "the precise requirement text to add, matching acceptance criteria, and the rationale. "
            "Return JSON with a single key 'suggestions' which is a list of objects, each containing: "
            "section_to_update (str), proposed_requirement_text (str), acceptance_criteria (list of str), reason_for_update (str).\n\n"
            f"Decision Title: {title}\n"
            f"Decision Summary: {summary}\n"
            f"Decision Reason: {reason}"
        )
        try:
            res = client._json_or_heuristic(prompt, lambda: {"suggestions": []})
            if "suggestions" in res:
                return res
        except Exception:
            pass

    return {
        "suggestions": [
            {
                "section_to_update": "Features / Functional Requirements",
                "proposed_requirement_text": f"The system shall support: {title}.",
                "acceptance_criteria": [
                    f"Validate that {title} functions correctly in all environments.",
                    "Verify corresponding database models are updated.",
                ],
                "reason_for_update": f"Agreed by team: {reason or summary or 'For project development alignment'}.",
            }
        ]
    }


def get_project_health(
    workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    repo = get_repository()
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    
    tasks = repo.list_tasks(workspace_id, channel_id)
    blockers = repo.list_blockers(workspace_id, channel_id)
    decisions = repo.list_decisions(workspace_id, channel_id)
    conflicts = repo.list_conflicts(workspace_id, channel_id)
    
    open_tasks = [t for t in tasks if t.get("status") not in ("done", "cancelled", "archived")]
    blocked_tasks = [t for t in open_tasks if t.get("id") in [b.get("task_id") for b in blockers if b.get("status") == "open"]]
    open_blockers = [b for b in blockers if b.get("status") == "open"]
    unresolved_conflicts = [c for c in conflicts if c.get("status") in ("open", "reopened_decision")]
    
    stale_decisions = []
    recent_confirmed_decisions = []
    
    for dec in decisions:
        if dec.get("status") == "confirmed":
            created_at_str = dec.get("created_at")
            if created_at_str:
                try:
                    if isinstance(created_at_str, str):
                        created_at = datetime.datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    else:
                        created_at = created_at_str
                    delta_days = (now - created_at).days
                    if delta_days > 30:
                        stale_decisions.append(dec)
                    if delta_days <= 7:
                        recent_confirmed_decisions.append(dec)
                except Exception:
                    pass
                    
    overdue_deadlines = []
    for t in tasks:
        if t.get("status") not in ("done", "cancelled", "archived"):
            due = t.get("due_date")
            if due:
                try:
                    if isinstance(due, str):
                        due_date = datetime.datetime.strptime(due, "%Y-%m-%d").date()
                    else:
                        due_date = due
                    if due_date < now.date():
                        overdue_deadlines.append(t)
                except Exception:
                    pass

    if unresolved_conflicts or overdue_deadlines or len(open_blockers) > 0:
        health_status = "Red"
    elif len(blocked_tasks) > 0 or len(stale_decisions) > 0 or len(open_tasks) > 5:
        health_status = "Yellow"
    else:
        health_status = "Green"
        
    return {
        "open_tasks_count": len(open_tasks),
        "blocked_tasks_count": len(blocked_tasks),
        "open_blockers_count": len(open_blockers),
        "unresolved_conflicts_count": len(unresolved_conflicts),
        "stale_decisions_count": len(stale_decisions),
        "recent_decisions_count": len(recent_confirmed_decisions),
        "overdue_deadlines_count": len(overdue_deadlines),
        "health_status": health_status,
        "stale_decisions": stale_decisions,
        "recent_confirmed_decisions": recent_confirmed_decisions,
        "open_blockers": open_blockers,
        "unresolved_conflicts": unresolved_conflicts,
        "overdue_deadlines": overdue_deadlines,
    }


# Dispatch table used by both the MCP server and the local fallback client.
DISPATCH = {
    "detect_decision": detect_decision,
    "save_decision": save_decision,
    "search_memory": search_memory,
    "detect_conflict": detect_conflict,
    "verify_evidence": verify_evidence,
    "generate_answer": generate_answer,
    "generate_project_summary": generate_project_summary,
    "reopen_decision": reopen_decision,
    "log_conflict_action": log_conflict_action,
    "get_decision_timeline": get_decision_timeline,
    "get_cleanup_suggestions": get_cleanup_suggestions,
    "execute_cleanup_action": execute_cleanup_action,
    "generate_prd_suggestions": generate_prd_suggestions,
    "get_project_health": get_project_health,
}


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in DISPATCH:
        raise KeyError(f"Unknown tool: {name}")
    return DISPATCH[name](**arguments)

