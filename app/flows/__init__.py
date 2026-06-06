"""Core agent flows: ask, decision detection, conflict detection, summary.

Each flow orchestrates the intent router, MCP tools, and (optionally) live Slack
evidence into a plain-dict result the Slack layer renders into Block Kit. Flows
are transport-agnostic and fully testable without Slack.
"""
from .ask import answer_question
from .conflict import check_conflict
from .decision import confirm_decision, detect_and_propose
from .summary import project_summary

__all__ = [
    "answer_question",
    "check_conflict",
    "confirm_decision",
    "detect_and_propose",
    "project_summary",
]
