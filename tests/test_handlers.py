"""Tests for Slack handler helpers: event idempotency and decision payload decode."""
from app.slack import cards
from app.slack import handlers
from app.store import get_store


async def test_duplicate_event_detection():
    store = get_store()
    assert await store.seen("evt-1") is False  # first time
    assert await store.seen("evt-1") is True   # retry/redelivery
    assert await store.seen("evt-2") is False  # different event
    assert await store.seen(None) is False     # missing id never dedupes


def test_decision_value_roundtrip_preserves_payload_and_is_searchable():
    decision = {
        "title": "Database Technology Decision for v1",
        "summary": "The team finalized the database choice.",
        "reason": "Phrasing indicates a final decision.",
        "confidence": 0.9,
        "original_message": "Okay final, PostgreSQL for v1.",
    }
    blocks = cards.decision_card(decision)
    confirm_value = blocks[2]["elements"][0]["value"]

    decoded = handlers._decision_from_value(confirm_value)
    assert decoded["title"] == decision["title"]
    assert decoded["reason"] == decision["reason"]
    # original message folded into summary so search can match its keywords
    assert "postgresql" in decoded["summary"].lower()


def test_decision_value_fallback_for_plain_string():
    decoded = handlers._decision_from_value("Just a title")
    assert decoded["title"] == "Just a title"


def test_decision_value_is_under_slack_limit():
    decision = {
        "title": "t",
        "summary": "s" * 5000,
        "reason": "r" * 5000,
        "original_message": "m" * 5000,
    }
    blocks = cards.decision_card(decision)
    assert len(blocks[2]["elements"][0]["value"]) <= 2000
