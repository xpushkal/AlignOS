"""End-to-end tests over the agent flows using the in-memory backend.

These mirror the demo script (PRD §28): detect a decision, confirm it, answer
from memory, then detect a conflict — all offline (no Slack, DB, or LLM key).
"""
import pytest

from app import flows
from app.db import reset_repository

WS = "T_TEST"
CH = "C_TEST"


@pytest.fixture(autouse=True)
def fresh_repo():
    reset_repository()
    yield
    reset_repository()


async def _confirm_postgres_decision():
    proposal = await flows.detect_and_propose(
        "Okay final, PostgreSQL for v1.", WS, CH
    )
    assert proposal["proposed"] is True
    saved = await flows.confirm_decision(proposal["decision"], WS, CH, confirmed_by="U1")
    assert saved["status"] == "confirmed"
    return saved


async def test_decision_detection_and_save():
    saved = await _confirm_postgres_decision()
    assert saved["decision_id"]


async def test_brainstorming_is_not_a_decision():
    proposal = await flows.detect_and_propose(
        "Should we use PostgreSQL or MongoDB?", WS, CH
    )
    assert proposal["proposed"] is False


async def test_answer_from_memory():
    await _confirm_postgres_decision()
    result = await flows.answer_question("what did we decide about postgresql?", WS, CH)
    assert result["refused"] is False
    assert "postgresql" in result["answer"].lower()
    assert result["source"] == "confirmed memory"


async def test_no_evidence_refusal():
    result = await flows.answer_question("did we finalize pricing?", WS, CH)
    assert result["refused"] is True
    assert result["support_level"] == "INSUFFICIENT_EVIDENCE"


async def test_conflict_detection():
    await _confirm_postgres_decision()
    conflict = await flows.check_conflict("I'll start MongoDB setup.", WS, CH, message_ts="123.45")
    assert conflict["conflict"] is True
    assert conflict["detection"]["conflict_type"] == "technology_choice"
    assert conflict["conflict_id"]


async def test_summary_lists_confirmed_decision():
    await _confirm_postgres_decision()
    summary = await flows.project_summary(WS, CH)
    titles = [d["title"].lower() for d in summary["confirmed_decisions"]]
    assert any("postgresql" in t for t in titles)


# --- cost gates: the LLM must be skipped on plain chatter ---
async def test_decision_gate_skips_llm_without_cue(monkeypatch):
    from app.flows import decision as decision_flow

    calls = []

    async def spy(name, args):
        calls.append(name)
        return {"is_decision": True, "confidence": 0.9}

    monkeypatch.setattr(decision_flow.mcp_client, "call_tool", spy)
    result = await flows.detect_and_propose("anyone up for lunch at 1?", WS, CH)
    assert result["proposed"] is False
    assert calls == []  # no LLM/tool call at all


async def test_decision_gate_runs_llm_with_cue(monkeypatch):
    from app.flows import decision as decision_flow

    calls = []

    async def spy(name, args):
        calls.append(name)
        return {"is_decision": True, "confidence": 0.9, "title": "x"}

    monkeypatch.setattr(decision_flow.mcp_client, "call_tool", spy)
    await flows.detect_and_propose("Okay we'll use Postgres for v1.", WS, CH)
    assert "detect_decision" in calls


async def test_conflict_gate_skips_llm_without_signal(monkeypatch):
    from app.flows import conflict as conflict_flow

    calls = []

    async def spy(name, args):
        calls.append(name)
        if name == "search_memory":
            return {"memory_items": []}
        return {}

    monkeypatch.setattr(conflict_flow.mcp_client, "call_tool", spy)
    # empty in-memory repo (autouse reset) -> no signal -> no detect_conflict call
    result = await flows.check_conflict("random unrelated chatter", WS, CH)
    assert result["conflict"] is False
    assert "detect_conflict" not in calls
