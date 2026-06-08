"""Core agent flows: ask, decision detection, conflict detection, summary.

Each flow orchestrates the intent router, MCP tools, and (optionally) live Slack
evidence into a plain-dict result the Slack layer renders into Block Kit. Flows
are transport-agnostic and fully testable without Slack.
"""
from .ask import answer_question
from .conflict import check_conflict
from .decision import confirm_decision, detect_and_propose
from .summary import project_summary
from .timeline import get_timeline
from .cleanup import get_cleanup_suggestions, execute_action
from .execution import generate_plan, persist_plan
from .health import get_health_summary
from .prd import get_prd_suggestions, apply_prd_suggestions
from .reminder import detect_reminder, schedule_reminder, check_reminders_and_send

__all__ = [
    "answer_question",
    "check_conflict",
    "confirm_decision",
    "detect_and_propose",
    "project_summary",
    "get_timeline",
    "get_cleanup_suggestions",
    "execute_action",
    "generate_plan",
    "persist_plan",
    "get_health_summary",
    "get_prd_suggestions",
    "apply_prd_suggestions",
    "detect_reminder",
    "schedule_reminder",
    "check_reminders_and_send",
]

