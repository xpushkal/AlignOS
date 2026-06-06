"""Block Kit card builders (PRD §13.6, §21.3).

Pure functions returning Slack Block Kit block lists, so they can be unit-tested
without a Slack connection.
"""
from __future__ import annotations

from typing import Any

Blocks = list[dict[str, Any]]


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


def decision_card(decision: dict[str, Any]) -> Blocks:
    """Decision confirmation card: Confirm / Edit / Reject (PRD §9.2)."""
    title = decision.get("title", "Untitled decision")
    reason = decision.get("reason") or "—"
    confidence = decision.get("confidence", 0.0)
    value = decision.get("id", title)
    return [
        _section(":memo: *Possible decision detected*"),
        _section(f"*Decision:* {title}\n*Reason:* {reason}\n*Confidence:* {confidence}"),
        {
            "type": "actions",
            "block_id": "decision_actions",
            "elements": [
                _button("Confirm", "decision_confirm", value, style="primary"),
                _button("Edit", "decision_edit", value),
                _button("Reject", "decision_reject", value, style="danger"),
            ],
        },
    ]


def conflict_card(detection: dict[str, Any], conflict_id: str) -> Blocks:
    """Conflict alert card: Remind / Reopen / Ignore (PRD §9.4)."""
    explanation = detection.get("explanation", "This message may contradict confirmed memory.")
    severity = detection.get("severity", "medium")
    return [
        _section(":warning: *Possible conflict detected*"),
        _section(f"{explanation}\n*Severity:* {severity}"),
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


def answer_blocks(result: dict[str, Any]) -> Blocks:
    """Render an ask-flow answer with confidence + source (PRD §14.5)."""
    if result.get("refused"):
        blocks = [_section(f":mag: {result['answer']}")]
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
    return [_section(result.get("answer", "")), _section(footer)]


def summary_blocks(summary: dict[str, Any]) -> Blocks:
    """Render the project memory summary (PRD §9.5)."""
    def names(items: list[dict]) -> str:
        return "\n".join(f"• {i.get('title', '')}" for i in items) or "_none_"

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
            "• `@AlignOS reopen <topic> decision`"
        ),
    ]
