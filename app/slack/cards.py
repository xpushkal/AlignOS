"""Block Kit card builders (PRD §13.6, §21.3).

Pure functions returning Slack Block Kit block lists, so they can be unit-tested
without a Slack connection.
"""
from __future__ import annotations

import json
from typing import Any

from app.security import escape_slack

Blocks = list[dict[str, Any]]

# Slack button `value` has a 2000-char limit; keep the encoded decision well under.
_VALUE_MAX = 1900


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(text: str, action_id: str, value: str, style: str | None = None) -> dict[str, Any]:
    btn = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "action_id": action_id,
        "value": value,
    }
    if style:
        btn["style"] = style
    return btn


def decision_card(decision: dict[str, Any], related_decision_id: str | None = None) -> Blocks:
    """Decision confirmation card with PRD alerts and Reopen actions (Feature 3, Feature 8)."""
    title = escape_slack(decision.get("title", "Untitled decision"))
    reason = escape_slack(decision.get("reason") or "—")
    confidence = decision.get("confidence", 0.0)
    
    payload = {
        "title": decision.get("title", ""),
        "summary": decision.get("summary", ""),
        "reason": decision.get("reason", ""),
        "confidence": decision.get("confidence"),
        "original_message": (decision.get("original_message") or "")[:600],
    }
    value = json.dumps(payload)[:_VALUE_MAX]
    
    blocks = [
        _section(":memo: *Possible decision detected*"),
        _section(f"*Decision:* {title}\n*Reason:* {reason}\n*Confidence:* {confidence}"),
    ]

    # PRD Warning (Feature 8)
    if decision.get("prd_impact"):
        blocks.append(_section(":warning: *PRD Impact Warning:* This decision may change PRD requirements. Suggesting updates is recommended."))

    action_elements = [
        _button("Confirm", "decision_confirm", value, style="primary"),
        _button("Edit", "decision_edit", value),
        _button("Reject", "decision_reject", value, style="danger"),
    ]
    
    # Reopen related button (Feature 3)
    reopen_val = related_decision_id or title
    action_elements.append(_button("Reopen Related", "decision_reopen_related", reopen_val))

    blocks.append({
        "type": "actions",
        "block_id": "decision_actions",
        "elements": action_elements,
    })
    return blocks


def conflict_card(detection: dict[str, Any], conflict_id: str) -> Blocks:
    """Conflict alert card with severity levels (Feature 2)."""
    explanation = escape_slack(
        detection.get("explanation", "This message may contradict confirmed memory.")
    )
    severity = detection.get("severity", "medium").lower()
    
    # Severity Badge
    severity_badges = {
        "low": ":large_blue_circle: *LOW*",
        "medium": ":large_orange_circle: *MEDIUM*",
        "high": ":red_circle: *HIGH*",
        "critical": ":black_square_for_stop: *CRITICAL*",
    }
    badge = severity_badges.get(severity, ":question: *UNKNOWN*")
    
    return [
        _section(f":warning: *Possible conflict detected* (Severity: {badge})"),
        _section(explanation),
        {
            "type": "actions",
            "block_id": "conflict_actions",
            "elements": [
                _button("Remind Decision", "conflict_remind", conflict_id),
                _button("Reopen Decision", "conflict_reopen", conflict_id),
                _button("Ignore", "conflict_ignore", conflict_id),
            ],
        },
    ]


def timeline_blocks(timeline_data: list[dict[str, Any]]) -> Blocks:
    """Render a chronological timeline of decisions (Feature 1)."""
    blocks = [_section(":hourglass_flowing_sand: *Confirmed Decision Timeline*")]
    if not timeline_data:
        blocks.append(_section("_No confirmed decisions found._"))
        return blocks

    for d in timeline_data:
        title = escape_slack(d.get("title", ""))
        status = escape_slack(d.get("status", ""))
        created = escape_slack(str(d.get("created_at", ""))[:19])
        reason = escape_slack(d.get("reason") or "No reason provided")
        evidence_count = d.get("evidence_count", 0)
        
        blocks.append(
            _section(
                f"⏰ *{created}* | *{title}*\n"
                f"• *Status:* `{status}`\n"
                f"• *Why Accepted:* {reason}\n"
                f"• *Evidence Links:* {evidence_count} messages attached"
            )
        )
    return blocks


def decision_comparison_card(
    old_decision: dict[str, Any],
    new_decision: dict[str, Any],
    explanation: str,
    conflict_id: str,
) -> Blocks:
    """Decision comparison card showing diff between old vs new decisions (Feature 6)."""
    old_title = escape_slack(old_decision.get("title", ""))
    old_reason = escape_slack(old_decision.get("reason", ""))
    new_title = escape_slack(new_decision.get("title", ""))
    new_reason = escape_slack(new_decision.get("reason", ""))
    
    # Encode both details
    payload = {
        "old_id": old_decision.get("id"),
        "new_decision": new_decision,
        "conflict_id": conflict_id,
    }
    val = json.dumps(payload)[:_VALUE_MAX]
    
    return [
        _section(":recycle: *New vs Old Decision Comparison*"),
        _section(f"*Explanation:* {escape_slack(explanation)}"),
        _section(f"🔴 *Old Decision:* {old_title}\n*Reason:* {old_reason}"),
        _section(f"🟢 *New Proposed Decision:* {new_title}\n*Reason:* {new_reason}"),
        {
            "type": "actions",
            "block_id": "comparison_actions",
            "elements": [
                _button("Supersede Old Decision", "decision_supersede", val, style="primary"),
                _button("Keep Both", "decision_keep_both", val),
                _button("Mark Conflict", "decision_mark_conflict", val, style="danger"),
                _button("Ignore", "conflict_ignore", conflict_id),
            ],
        },
    ]


def cleanup_suggestions_card(suggestions: dict[str, Any]) -> Blocks:
    """Render memory hygiene suggestions (Feature 4)."""
    blocks = [_section(":broom: *AlignOS Memory Hygiene Suggestions*")]
    
    stale = suggestions.get("stale_decisions", [])
    duplicates = suggestions.get("duplicate_tasks", [])
    completed = suggestions.get("completed_tasks", [])
    low_conf = suggestions.get("low_confidence", [])

    if not (stale or duplicates or completed or low_conf):
        blocks.append(_section("_Memory is fully cleaned up! No suggestions._"))
        return blocks

    # Stale decisions
    if stale:
        blocks.append(_section("⏰ *Stale Decisions (>30 days old):*"))
        for item in stale[:3]:
            iid = item["id"]
            blocks.append(
                _section(
                    f"• {escape_slack(item['title'])} (Created: {str(item['created_at'])[:10]})\n"
                    f"Action: <@AlignOS> action buttons:"
                )
            )
            blocks.append({
                "type": "actions",
                "block_id": f"stale_actions_{iid}",
                "elements": [
                    _button("Archive", "cleanup_archive", iid),
                    _button("Delete", "cleanup_delete", iid, style="danger"),
                    _button("Ignore", "cleanup_ignore", iid),
                ],
            })

    # Duplicate tasks
    if duplicates:
        blocks.append(_section("👯 *Duplicate Task Groups:*"))
        for idx, group in enumerate(duplicates[:3]):
            desc = "\n".join(f" - {escape_slack(t['title'])} (ID: {t['id'][:8]})" for t in group)
            blocks.append(_section(f"Group {idx+1}:\n{desc}"))
            
            # Button value carries primary:duplicate
            val = f"{group[0]['id']}:{group[1]['id']}"
            blocks.append({
                "type": "actions",
                "block_id": f"dup_actions_{idx}",
                "elements": [
                    _button("Merge Tasks", "cleanup_merge", val, style="primary"),
                    _button("Ignore", "cleanup_ignore", group[0]['id']),
                ],
            })

    # Completed tasks
    if completed:
        blocks.append(_section("✅ *Completed Old Tasks (>14 days old):*"))
        for item in completed[:3]:
            iid = item["id"]
            blocks.append(_section(f"• {escape_slack(item['title'])}"))
            blocks.append({
                "type": "actions",
                "block_id": f"comp_actions_{iid}",
                "elements": [
                    _button("Archive", "cleanup_archive", iid),
                    _button("Delete", "cleanup_delete", iid, style="danger"),
                    _button("Ignore", "cleanup_ignore", iid),
                ],
            })

    # Low confidence
    if low_conf:
        blocks.append(_section("⚠️ *Low Confidence or Rejected Items:*"))
        for item in low_conf[:3]:
            iid = item["id"]
            blocks.append(_section(f"• {escape_slack(item['title'])} (Status: {item.get('status')})"))
            blocks.append({
                "type": "actions",
                "block_id": f"low_actions_{iid}",
                "elements": [
                    _button("Delete", "cleanup_delete", iid, style="danger"),
                    _button("Ignore", "cleanup_ignore", iid),
                ],
            })

    return blocks


def execution_plan_card(plan: dict[str, Any], cache_key: str) -> Blocks:
    """Render proposed execution plan from meeting thread (Feature 5)."""
    summary = escape_slack(plan.get("summary", ""))
    
    decisions = "\n".join(f"• *{escape_slack(d['title'])}* (Why: {escape_slack(d['reason'])})" for d in plan.get("decisions", [])) or "_none_"
    tasks = "\n".join(f"• *{escape_slack(t['title'])}* (Owner: {escape_slack(t['owner'])}, Due: {escape_slack(t.get('deadline') or 'none')})" for t in plan.get("action_items", [])) or "_none_"
    blockers = "\n".join(f"• *{escape_slack(b['title'])}* ({escape_slack(b['description'])})" for b in plan.get("blockers", [])) or "_none_"
    next_steps = "\n".join(f"• {escape_slack(ns)}" for ns in plan.get("next_steps", [])) or "_none_"

    return [
        _section(":rocket: *Proposed Meeting Execution Plan*"),
        _section(f"*Summary:* {summary}"),
        _section(f"*Decisions to Save:*\n{decisions}"),
        _section(f"*Tasks to Extract:*\n{tasks}"),
        _section(f"*Blockers Identified:*\n{blockers}"),
        _section(f"*Next Steps:*\n{next_steps}"),
        {
            "type": "actions",
            "block_id": "execution_actions",
            "elements": [
                _button("Persist Plan to Memory", "execution_persist", cache_key, style="primary"),
                _button("Ignore", "evidence_ignore", "ignore"),
            ],
        },
    ]


def project_health_card(health: dict[str, Any]) -> Blocks:
    """Render project health scan card (Feature 7)."""
    status = health.get("health_status", "Green")
    status_emojis = {
        "Green": "🟢 *HEALTHY (GREEN)*",
        "Yellow": "🟡 *WARNING (YELLOW)*",
        "Red": "🔴 *CRITICAL (RED)*",
    }
    badge = status_emojis.get(status, status)

    return [
        _section(f":heartbeat: *Project Health Check* | Status: {badge}"),
        _section(
            f"• *Open Tasks:* {health.get('open_tasks_count')} tasks\n"
            f"• *Blocked Tasks:* {health.get('blocked_tasks_count')} tasks\n"
            f"• *Open Blockers:* {health.get('open_blockers_count')} blockers\n"
            f"• *Unresolved Conflicts:* {health.get('unresolved_conflicts_count')} conflicts\n"
            f"• *Overdue Deadlines:* {health.get('overdue_deadlines_count')} tasks\n"
            f"• *Stale Decisions:* {health.get('stale_decisions_count')} items"
        ),
    ]


def prd_suggestions_blocks(suggestions: list[dict[str, Any]], cache_key: str) -> Blocks:
    """Render PRD suggestion changes card (Feature 8)."""
    blocks = [_section(":notebook: *Suggested PRD Requirements Changes*")]
    for idx, sug in enumerate(suggestions):
        sect = escape_slack(sug.get("section_to_update", ""))
        req = escape_slack(sug.get("proposed_requirement_text", ""))
        criteria = "\n".join(f" - {escape_slack(c)}" for c in sug.get("acceptance_criteria", []))
        reason = escape_slack(sug.get("reason_for_update", ""))
        
        blocks.append(
            _section(
                f"*Suggestion {idx+1} in Section: {sect}*\n"
                f"*Proposed Requirement:* {req}\n"
                f"*Acceptance Criteria:*\n{criteria}\n"
                f"*Rationale:* {reason}"
            )
        )
    blocks.append({
        "type": "actions",
        "block_id": "prd_actions",
        "elements": [
            _button("Apply to prd.md", "prd_apply", cache_key, style="primary"),
            _button("Reject Suggestions", "evidence_ignore", "ignore"),
        ],
    })
    return blocks


def answer_blocks(result: dict[str, Any]) -> Blocks:
    """Render an ask-flow answer with confidence + source (PRD §14.5)."""
    if result.get("refused"):
        blocks = [_section(f":mag: {escape_slack(result['answer'])}")]
        blocks.append(
            {
                "type": "actions",
                "block_id": "no_evidence_actions",
                "elements": [
                    _button("Start Decision Thread", "evidence_start_thread", "start"),
                    _button("Search Again", "evidence_search_again", "search"),
                    _button("Ignore", "evidence_ignore", "ignore"),
                ],
            }
        )
        return blocks
    footer = f"_Confidence: {result.get('confidence')} · Source: {result.get('source')}_"
    return [_section(escape_slack(result.get("answer", ""))), _section(footer)]


def summary_blocks(summary: dict[str, Any]) -> Blocks:
    """Render the project memory summary (PRD §9.5)."""
    def names(items: list[dict]) -> str:
        return "\n".join(f"• {escape_slack(i.get('title', ''))}" for i in items) or "_none_"

    return [
        _section(":card_index_dividers: *Project Memory*"),
        _section("*Confirmed decisions:*\n" + names(summary.get("confirmed_decisions", []))),
        _section("*Open tasks:*\n" + names(summary.get("open_tasks", []))),
        _section("*Blockers:*\n" + names(summary.get("blockers", []))),
        _section("*Unresolved questions:*\n" + names(summary.get("unresolved_questions", []))),
    ]


def help_blocks() -> Blocks:
    return [
        _section(":wave: *AlignOS* — turn Slack chaos into verified team memory."),
        _section(
            "*Try:*\n"
            "• `@AlignOS what did we decide about <topic>?`\n"
            "• `@AlignOS show project memory`\n"
            "• `@AlignOS show conflicts`\n"
            "• `@AlignOS reopen <topic> decision`\n"
            "• `@AlignOS timeline`\n"
            "• `@AlignOS project health`\n"
            "• `@AlignOS turn this thread into execution plan`\n"
            "• `@AlignOS memory cleanup`"
        ),
    ]

