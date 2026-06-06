"""Deterministic rule-based fallbacks for the LLM reasoning tasks.

These keep AlignOS fully functional offline (no API key) for local dev, tests,
and demos. They are intentionally simple and conservative — they bias toward
"needs confirmation" and "insufficient evidence" rather than inventing facts,
matching the no-hallucination guardrails in Docs/MCP_TOOLS.md §4.
"""
from __future__ import annotations

import re
from typing import Any

# Phrases that signal a finalized decision (PRD §9.2).
DECISION_CUES = [
    "let's finalize",
    "lets finalize",
    "finalize",
    "finalized",
    "we agreed",
    "agreed on",
    "final decision",
    "okay, we'll use",
    "we'll use",
    "let's go with",
    "lets go with",
    "going with",
    "go with",
    "settled on",
    "stick with",
    "sticking with",
    "deadline is fixed",
    "we are dropping",
    "we're dropping",
    "final then",
    "for v1",
    "let's use",
    "lets use",
    "decided",
    "decision is",
]


def has_decision_cue(message: str) -> bool:
    """Cheap gate: does the message look decision-like at all?

    Used to skip the (expensive) LLM decision classifier on the ~majority of
    messages that contain no decision language.
    """
    text = message.lower()
    return any(cue in text for cue in DECISION_CUES)


def has_conflict_signal(message: str, memory_items: list[dict]) -> bool:
    """Cheap gate: is there a plausible contradiction worth an LLM review?

    Reuses the rule-based conflict engine (opposing technology terms etc.) so we
    only escalate to the LLM when there's an actual signal.
    """
    return bool(memory_items) and detect_conflict(message, memory_items)["is_conflict"]


def detect_decision(message: str) -> dict[str, Any]:
    text = message.lower()
    hits = [cue for cue in DECISION_CUES if cue in text]
    is_decision = len(hits) > 0
    confidence = min(0.5 + 0.15 * len(hits), 0.95) if is_decision else 0.1
    title = _title_from(message) if is_decision else ""
    return {
        "is_decision": is_decision,
        "title": title,
        "summary": message.strip() if is_decision else "",
        "reason": "",
        "participants": [],
        "confidence": round(confidence, 2),
        "needs_confirmation": is_decision,
    }


def verify_evidence(
    evidence_messages: list[str], memory_items: list[dict]
) -> dict[str, Any]:
    has_evidence = bool(evidence_messages) or bool(memory_items)
    if not has_evidence:
        return {
            "support_level": "INSUFFICIENT_EVIDENCE",
            "confidence": 0.1,
            "contradictions": [],
            "missing_evidence": ["No matching memory or Slack evidence found."],
            "safe_to_answer": False,
        }
    confidence = 0.85 if memory_items else 0.6
    return {
        "support_level": "SUPPORTED" if memory_items else "PARTIALLY_SUPPORTED",
        "confidence": confidence,
        "contradictions": [],
        "missing_evidence": [],
        "safe_to_answer": True,
    }


# Pairs of mutually-exclusive technology choices for conflict heuristics.
_OPPOSING_TERMS = [
    {"postgresql", "postgres", "mongodb", "mongo"},
    {"rest", "graphql"},
    {"aws", "gcp", "azure"},
]


def detect_conflict(new_message: str, confirmed_memory: list[dict]) -> dict[str, Any]:
    text = new_message.lower()
    for item in confirmed_memory:
        memory_text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        for group in _OPPOSING_TERMS:
            in_msg = {t for t in group if t in text}
            in_mem = {t for t in group if t in memory_text}
            # Conflict when the message names an option the memory does NOT endorse.
            if in_msg and in_mem and not (in_msg & in_mem):
                return {
                    "is_conflict": True,
                    "conflict_type": "technology_choice",
                    "severity": "medium",
                    "explanation": (
                        f"New message mentions {', '.join(in_msg)}, but confirmed "
                        f"memory says {', '.join(in_mem)}."
                    ),
                    "recommended_action": "remind_decision",
                    "conflicting_memory_id": item.get("id"),
                }
    return {
        "is_conflict": False,
        "conflict_type": None,
        "severity": "low",
        "explanation": "No contradiction with confirmed memory detected.",
        "recommended_action": None,
        "conflicting_memory_id": None,
    }


def answer(
    question: str, memory_items: list[dict], evidence_messages: list[str]
) -> dict[str, Any]:
    """Offline grounded-answer fallback.

    Prefers confirmed memory; treats live evidence as discussion (not a confirmed
    decision) and refuses rather than guessing when there is no confirmed memory
    (no-evidence refusal, PRD §9.6).
    """
    if memory_items:
        top = memory_items[0]
        title = (top.get("title") or "").strip()
        summary = (top.get("summary") or "").strip()
        text = f"{title}. {summary}".strip(". ").strip() or title or summary
        return {
            "answer": text,
            "support_level": "SUPPORTED",
            "confidence": 0.85,
            "refused": False,
        }
    return {
        "answer": (
            "I could not find enough confirmed evidence to answer that. "
            "I found discussion but no confirmed decision."
            if evidence_messages
            else "I could not find enough confirmed evidence to answer that."
        ),
        "support_level": "PARTIALLY_SUPPORTED" if evidence_messages else "INSUFFICIENT_EVIDENCE",
        "confidence": 0.3 if evidence_messages else 0.1,
        "refused": True,
    }


def _title_from(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip().rstrip(".")
    words = cleaned.split(" ")
    return " ".join(words[:10])
