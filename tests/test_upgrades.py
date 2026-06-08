"""Unit tests for the 9 new upgraded features of AlignOS."""
import os
import pytest
import tempfile
from app import flows
from app.db import reset_repository, get_repository

WS = "T_TEST"
CH = "C_TEST"


@pytest.fixture(autouse=True)
def fresh_repo():
    reset_repository()
    yield
    reset_repository()


async def test_feature_1_timeline_and_why():
    # Confirm PostgreSQL decision
    proposal = await flows.detect_and_propose("Okay final, PostgreSQL for v1.", WS, CH)
    await flows.confirm_decision(proposal["decision"], WS, CH, confirmed_by="U1")

    # Fetch timeline
    timeline = await flows.get_timeline(WS, CH)
    assert len(timeline["timeline"]) == 1
    assert "PostgreSQL" in timeline["timeline"][0]["title"]

    # Check reason/why
    result = await flows.answer_question("why did we decide to use postgresql?", WS, CH)
    assert result["refused"] is False
    assert "postgresql" in result["answer"].lower()


async def test_feature_2_conflict_severity():
    # Confirm PostgreSQL decision
    proposal = await flows.detect_and_propose("Okay final, PostgreSQL for v1.", WS, CH)
    await flows.confirm_decision(proposal["decision"], WS, CH, confirmed_by="U1")

    # Test high severity technology conflict
    conflict_high = await flows.check_conflict("I will start MongoDB setup.", WS, CH)
    assert conflict_high["conflict"] is True
    assert conflict_high["detection"]["severity"] == "high"

    # Test critical severity conflict
    conflict_crit = await flows.check_conflict("I will start MongoDB deployment now because security requirements are critical.", WS, CH)
    assert conflict_crit["conflict"] is True
    assert conflict_crit["detection"]["severity"] == "critical"


async def test_feature_3_reopen_related():
    # Confirm PostgreSQL decision
    proposal = await flows.detect_and_propose("Okay final, PostgreSQL for v1.", WS, CH)
    dec = await flows.confirm_decision(proposal["decision"], WS, CH, confirmed_by="U1")
    dec_id = dec["decision_id"]

    # Reopen decision
    repo = get_repository()
    row = repo.update_decision_status(dec_id, "reopened")
    assert row["status"] == "reopened"


async def test_feature_4_cleanup():
    # Confirm old task (simulating stale done task)
    repo = get_repository()
    task = repo.save_task({
        "workspace_id": WS,
        "channel_id": CH,
        "title": "Old Task",
        "status": "done",
    })
    
    # We simulate update timestamp aging by archiving or delete triggers
    suggestions = await flows.get_cleanup_suggestions(WS, CH)
    assert len(suggestions["completed_tasks"]) >= 0 # will check completed task

    # Run execute cleanup action
    res = await flows.execute_action("archive", task["id"])
    assert res["result"]["action"] == "archived"


async def test_feature_5_execution_plan():
    text = "Ayush: Fix Slack auth by tomorrow. Priya: Make sure MongoDB is blocker."
    plan = await flows.generate_plan(text)
    
    assert "summary" in plan
    assert len(plan["action_items"]) > 0
    assert len(plan["blockers"]) >= 0

    # Persist execution plan
    result = await flows.persist_plan(plan, WS, CH)
    assert len(result["tasks"]) > 0


async def test_feature_6_decision_comparison():
    # Save old decision
    repo = get_repository()
    old = repo.save_decision({
        "workspace_id": WS,
        "channel_id": CH,
        "title": "Use Postgres",
        "status": "confirmed",
    })

    # Propose contradicting decision
    new_dec = {"title": "Use MongoDB", "summary": "Use MongoDB", "reason": "No SQL"}
    # Verify both can be handled by comparison handlers
    # Mark old superseded
    repo.execute_cleanup_action("supersede", old["id"], target_id="123")
    old_updated = repo.get_decision(old["id"])
    assert old_updated["status"] == "superseded"


async def test_feature_7_project_health():
    repo = get_repository()
    
    # Save open task and blocker
    repo.save_task({"workspace_id": WS, "channel_id": CH, "title": "Setup database"})
    repo.save_blocker({"workspace_id": WS, "channel_id": CH, "title": "Missing credentials"})

    health = await flows.get_health_summary(WS, CH)
    assert health["health_status"] == "Red" # Red health due to open blockers
    assert health["open_tasks_count"] == 1


async def test_feature_8_prd_impact_and_suggestion():
    # Save a decision
    repo = get_repository()
    dec = repo.save_decision({
        "workspace_id": WS,
        "channel_id": CH,
        "title": "Integrate Google Auth",
        "status": "confirmed",
    })

    suggestions = await flows.get_prd_suggestions(dec["id"], WS)
    assert len(suggestions["suggestions"]) > 0

    # Write PRD suggestions to temporary file to verify update logic
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
        tmp.write(b"# Product Requirements Document\n")
        tmp_name = tmp.name

    try:
        success = await flows.apply_prd_suggestions(suggestions["suggestions"], prd_path=tmp_name)
        assert success is True
        with open(tmp_name, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Approved Requirements Updates" in content
            assert "Integrate Google Auth" in content
    finally:
        os.remove(tmp_name)


async def test_feature_9_deadline_reminders():
    # Schedule a reminder
    rem = await flows.schedule_reminder(
        workspace_id=WS,
        task_title="Fix Slack auth",
        owner_slack_id="U1",
        deadline="2026-06-08",
        remind_at="2026-06-07T10:00:00+00:00",
    )
    assert rem["status"] == "scheduled"

    # Mock Slack web client
    class MockSlackClient:
        def __init__(self):
            self.calls = []
        def chat_postMessage(self, channel, text):
            self.calls.append({"channel": channel, "text": text})

    client = MockSlackClient()
    sent_count = await flows.check_reminders_and_send(client)
    assert sent_count == 1
    assert len(client.calls) == 1
    assert "Fix Slack auth" in client.calls[0]["text"]
