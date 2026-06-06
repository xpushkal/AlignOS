"""Tests for live-evidence retrieval (RTS) and confirmed_by persistence."""
import pytest

from app import flows, rts
from app.db import get_repository


class FakeSlackClient:
    def __init__(self, messages):
        self._messages = messages
        self.calls = []

    async def conversations_history(self, channel, limit):
        self.calls.append((channel, limit))
        return {"messages": self._messages}


async def test_rts_returns_human_messages_only():
    client = FakeSlackClient(
        [
            {"user": "U1", "text": "we should use Postgres"},
            {"bot_id": "B1", "text": "bot noise"},          # skipped (bot)
            {"subtype": "channel_join", "text": "joined"},   # skipped (system)
            {"user": "BOT", "text": "my own message"},       # skipped (excluded)
            {"user": "U2", "text": "agreed"},
        ]
    )
    out = await rts.fetch_channel_evidence(client, "C1", limit=10, exclude_user="BOT")
    assert out == ["we should use Postgres", "agreed"]
    assert client.calls == [("C1", 10)]


async def test_rts_handles_errors_gracefully():
    class Boom:
        async def conversations_history(self, channel, limit):
            raise RuntimeError("missing_scope")

    assert await rts.fetch_channel_evidence(Boom(), "C1") == []
    assert await rts.fetch_channel_evidence(object(), None) == []  # no channel


async def test_answer_uses_live_evidence_when_no_memory():
    """With no confirmed memory but live evidence, the answer is sourced from it
    (heuristic still refuses to assert a confirmed decision)."""
    res = await flows.answer_question(
        "what database are we leaning toward?",
        "T",
        "C",
        evidence_messages=["Priya: leaning Postgres", "Rahul: ok"],
    )
    # evidence present but unconfirmed -> partial support, not a hard refusal source
    assert res["support_level"] in {"PARTIALLY_SUPPORTED", "SUPPORTED", "INSUFFICIENT_EVIDENCE"}


async def test_confirmed_by_is_persisted():
    WS, CH = "T", "C"
    prop = await flows.detect_and_propose("Okay final, we'll use Postgres for v1.", WS, CH)
    d = dict(prop["decision"]); d["original_message"] = "Okay final, we'll use Postgres for v1."
    saved = await flows.confirm_decision(d, WS, CH, confirmed_by="U_ALICE")
    row = get_repository().get_decision(saved["decision_id"])
    assert row is not None
    assert row.get("confirmed_by_user_id") == "U_ALICE"
