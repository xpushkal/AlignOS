import os
import json
import shutil
from dotenv import load_dotenv

# Load env variables from .env file in the same directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Set temporary db path for testing
test_db_path = "test_alignos.db"
if os.path.exists(test_db_path):
    os.remove(test_db_path)

os.environ["DB_PATH"] = test_db_path

# Check if OPENROUTER_API_KEY is populated
api_key = os.environ.get("OPENROUTER_API_KEY")
if not api_key or api_key == "your-openrouter-api-key" or api_key.strip() == "":
    os.environ["OPENROUTER_API_KEY"] = ""  # Force mock mode
    print("Running tests in MOCK mode.")
else:
    print(f"Running tests in LIVE API mode with model: {os.environ.get('OPENROUTER_MODEL', 'google/gemini-2.5-flash')}")

# Load imports after setting up environment
import database as db
import mcp_server as mcp_tools

def run_tests():
    print("==================================================")
    print("      AlignOS System Offline Verification        ")
    print("==================================================")

    # 1. Initialize Database
    db.init_db()
    
    # Verify tables created
    conn = db.get_db_connection()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    table_names = [t["name"] for t in tables]
    print(f"Database tables verified: {table_names}\n")
    conn.close()

    assert "decisions" in table_names
    assert "evidence_links" in table_names
    assert "conflicts" in table_names
    assert "tasks" in table_names
    assert "memory_items" in table_names

    # 2. Test detect_decision tool (on decision message)
    decision_msg = "Okay, final decision: let's use PostgreSQL for v1 since our data is structured."
    print(f"Testing detect_decision on: '{decision_msg}'")
    
    dec_res_json = mcp_tools.detect_decision(decision_msg, thread_context="Ayush: MongoDB or PostgreSQL?\nPriya: PostgreSQL is structured.")
    dec_res = json.loads(dec_res_json)
    
    print(f"Result: is_decision={dec_res.get('is_decision')}, title='{dec_res.get('title')}', confidence={dec_res.get('confidence')}")
    assert dec_res.get("is_decision") is True
    assert "PostgreSQL" in dec_res.get("title")
    print("[OK] detect_decision passed\n")

    # 3. Test save_decision tool
    print("Testing save_decision...")
    evidence = [
        {"slack_message_ts": "1717621000.0001", "slack_thread_ts": "1717620000.0000", "slack_user_id": "U123", "snippet": "Okay, final decision: let's use PostgreSQL for v1"},
        {"slack_message_ts": "1717620950.0002", "slack_thread_ts": "1717620000.0000", "slack_user_id": "U456", "snippet": "PostgreSQL is safer because our data is structured."}
    ]
    
    save_res_json = mcp_tools.save_decision(
        workspace_id="W001",
        channel_id="C001",
        thread_ts="1717620000.0000",
        title=dec_res.get("title"),
        summary=dec_res.get("summary"),
        reason=dec_res.get("reason"),
        status="confirmed",
        confidence=dec_res.get("confidence"),
        evidence_list_json=json.dumps(evidence)
    )
    save_res = json.loads(save_res_json)
    decision_id = save_res.get("decision_id")
    print(f"Saved decision with ID: {decision_id}")
    assert save_res.get("status") == "success"
    assert decision_id is not None
    
    # Check DB record
    record = db.get_decision(decision_id)
    print(f"Retrieved DB record: {record['title']} | Status: {record['status']}")
    assert record["status"] == "confirmed"
    
    # Check Evidence link
    ev_records = db.get_decision_evidence(decision_id)
    print(f"Retrieved DB evidence: {len(ev_records)} linked messages.")
    assert len(ev_records) == 2
    print("[OK] save_decision passed\n")

    # 4. Test search_memory tool
    print("Testing search_memory...")
    search_res_json = mcp_tools.search_memory(workspace_id="W001", channel_id="C001", query="PostgreSQL")
    search_res = json.loads(search_res_json)
    print(f"Found {len(search_res)} matching items.")
    assert len(search_res) == 1
    assert search_res[0]["id"] == decision_id
    print("[OK] search_memory passed\n")

    # 5. Test detect_conflict tool (with contradiction message)
    conflict_msg = "I'll start MongoDB setup now."
    print(f"Testing detect_conflict on: '{conflict_msg}'")
    
    conflict_res_json = mcp_tools.detect_conflict(
        workspace_id="W001",
        channel_id="C001",
        new_message=conflict_msg,
        message_ts="1717630000.0000"
    )
    conflict_res = json.loads(conflict_res_json)
    conflict_id = conflict_res.get("conflict_id")
    
    print(f"Result: is_conflict={conflict_res.get('is_conflict')}, explanation='{conflict_res.get('explanation')}', conflict_id={conflict_id}")
    assert conflict_res.get("is_conflict") is True
    assert conflict_id is not None
    
    # Check DB Conflict Record
    conflict_rec = db.get_conflict(conflict_id)
    print(f"Retrieved DB Conflict: type={conflict_rec['conflict_type']} | status={conflict_rec['status']}")
    assert conflict_rec["status"] == "open"
    print("[OK] detect_conflict passed\n")

    # 6. Test generate_project_summary tool
    print("Testing generate_project_summary...")
    # Add a mock task to DB first
    db.save_task(
        workspace_id="W001",
        channel_id="C001",
        title="Setup database connections",
        owner_user_id="U123",
        status="open",
        due_date="2026-06-10",
        evidence_message_ts="1717621000.0001"
    )
    
    summary_json = mcp_tools.generate_project_summary(workspace_id="W001", channel_id="C001")
    summary = json.loads(summary_json)
    print("Summary Output:")
    # Clean output to remove emoji
    summary_clean = summary.get("summary").replace("📊", "[BAR]").replace("⚠️", "[WARNING]")
    print(summary_clean)
    assert "PostgreSQL" in summary.get("summary")
    print("[OK] generate_project_summary passed\n")

    # 7. Test log_conflict_action (resolve & reopen)
    print("Testing conflict resolution action: reopen_decision...")
    action_res_json = mcp_tools.log_conflict_action(conflict_id=conflict_id, action="reopen_decision")
    action_res = json.loads(action_res_json)
    print(f"Action response: {action_res.get('message')}")
    assert action_res.get("status") == "success"
    
    # Verify conflict status updated
    conflict_rec = db.get_conflict(conflict_id)
    assert conflict_rec["status"] == "reopened_decision"
    
    # Verify decision status updated to reopened
    record = db.get_decision(decision_id)
    print(f"Re-retrieved decision status: {record['status']}")
    assert record["status"] == "reopened"
    print("[OK] log_conflict_action (reopen_decision) passed\n")

    # Clean up test database file
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        print("Test database cleaned up.")

    print("\n==================================================")
    print("      ALL OFFLINE SYSTEM TESTS PASSED!            ")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
