"""Intent routing for inbound Slack messages.

Classifies a message into one of the intents from PRD §13.2 using fast
rule-based checks first. Ambiguous cases can defer to the LLM (the seam is here);
for the MVP the rules cover the documented commands and the demo script.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

QUESTION_ANSWERING = "question_answering"
POSSIBLE_DECISION = "possible_decision"
POSSIBLE_CONFLICT = "possible_conflict"
SHOW_MEMORY = "show_memory"
SAVE_TASK = "save_task"
SUMMARIZE_THREAD = "summarize_thread"
SHOW_CONFLICTS = "show_conflicts"
REOPEN_DECISION = "reopen_decision"
SHOW_TIMELINE = "show_timeline"
MEETING_TO_EXECUTION = "meeting_to_execution"
CLEANUP_SUGGESTIONS = "cleanup_suggestions"
SHOW_HEALTH = "show_health"
HELP = "help"
UNKNOWN = "unknown"


@dataclass
class Intent:
    name: str
    confidence: float
    topic: str = ""


def _strip_mention(text: str) -> str:
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def classify(text: str) -> Intent:
    """Classify a (possibly mention-prefixed) message into an Intent."""
    cleaned = _strip_mention(text).strip()
    low = cleaned.lower()

    if not low:
        return Intent(UNKNOWN, 0.0)

    if low in {"help", "/alignos help"} or low.startswith("help"):
        return Intent(HELP, 0.95)

    if "show project memory" in low or low in {"memory", "/alignos memory"}:
        return Intent(SHOW_MEMORY, 0.95)

    if "show conflicts" in low or low in {"conflicts", "/alignos conflicts"}:
        return Intent(SHOW_CONFLICTS, 0.9)

    if "timeline" in low:
        return Intent(SHOW_TIMELINE, 0.9)

    if "execution plan" in low or "summarize this thread" in low or "turn this discussion" in low:
        return Intent(MEETING_TO_EXECUTION, 0.9)

    if "cleanup" in low:
        return Intent(CLEANUP_SUGGESTIONS, 0.9)

    if "health" in low:
        return Intent(SHOW_HEALTH, 0.9)

    if low.startswith("reopen") or "reopen" in low and "decision" in low:
        return Intent(REOPEN_DECISION, 0.85, topic=_topic_after(low, "reopen"))

    if low.startswith("summarize") or "summarize today" in low:
        return Intent(SUMMARIZE_THREAD, 0.8)

    # Questions: ends with '?' or starts with an interrogative.
    if cleaned.endswith("?") or re.match(r"^(what|why|who|when|where|how|did|is|are|do|does)\b", low):
        return Intent(QUESTION_ANSWERING, 0.8, topic=cleaned)

    return Intent(UNKNOWN, 0.3, topic=cleaned)



def _topic_after(text: str, keyword: str) -> str:
    idx = text.find(keyword)
    if idx == -1:
        return ""
    return text[idx + len(keyword):].replace("decision", "").strip()
