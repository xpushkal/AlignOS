import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "alignos.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Decisions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        thread_ts TEXT,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL CHECK(status IN ('proposed', 'confirmed', 'rejected', 'reopened', 'superseded')),
        confidence REAL,
        confirmed_by_user_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        supersedes_decision_id INTEGER,
        evidence_count INTEGER DEFAULT 0
    );
    """)

    # 2. Evidence Links Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evidence_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_item_id INTEGER NOT NULL,
        source_type TEXT NOT NULL, -- 'decision', 'task', 'blocker'
        slack_channel_id TEXT NOT NULL,
        slack_message_ts TEXT NOT NULL,
        slack_thread_ts TEXT,
        slack_user_id TEXT NOT NULL,
        snippet TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    # 3. Conflicts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conflicts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        message_ts TEXT NOT NULL,
        conflict_type TEXT NOT NULL,
        severity TEXT NOT NULL CHECK(severity IN ('low', 'medium', 'high')),
        new_message_summary TEXT NOT NULL,
        conflicting_memory_id INTEGER NOT NULL,
        explanation TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('open', 'ignored', 'resolved', 'reopened_decision')),
        created_at TEXT NOT NULL
    );
    """)

    # 4. Tasks Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        owner_user_id TEXT,
        status TEXT NOT NULL CHECK(status IN ('open', 'completed')),
        due_date TEXT,
        evidence_message_ts TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 5. Memory Items (General - summaries, blockers, unresolved questions)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('decision', 'task', 'blocker', 'deadline', 'question', 'summary')),
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL,
        confidence REAL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized successfully at: {DB_PATH}")

# CRUD Helpers for Decisions
def save_decision(workspace_id, channel_id, thread_ts, title, summary, reason, status, confidence, evidence_list=None, supersedes_decision_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    evidence_count = len(evidence_list) if evidence_list else 0

    cursor.execute("""
    INSERT INTO decisions (
        workspace_id, channel_id, thread_ts, title, summary, reason, status, confidence, created_at, updated_at, supersedes_decision_id, evidence_count
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workspace_id, channel_id, thread_ts, title, summary, reason, status, confidence, now_str, now_str, supersedes_decision_id, evidence_count
    ))
    decision_id = cursor.lastrowid

    # If it supersedes an old decision, mark the old one as superseded
    if supersedes_decision_id:
        cursor.execute("""
        UPDATE decisions SET status = 'superseded', updated_at = ? WHERE id = ?
        """, (now_str, supersedes_decision_id))

    # Save evidence links if any
    if evidence_list:
        for ev in evidence_list:
            cursor.execute("""
            INSERT INTO evidence_links (
                memory_item_id, source_type, slack_channel_id, slack_message_ts, slack_thread_ts, slack_user_id, snippet, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision_id, 'decision', channel_id, ev.get("slack_message_ts"), ev.get("slack_thread_ts"), ev.get("slack_user_id"), ev.get("snippet", ""), now_str
            ))

    conn.commit()
    conn.close()
    return decision_id

def get_decision(decision_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_decision_evidence(decision_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM evidence_links WHERE memory_item_id = ? AND source_type = 'decision'", (decision_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_decision_status(decision_id, status, confirmed_by_user_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    if confirmed_by_user_id:
        cursor.execute("""
        UPDATE decisions SET status = ?, confirmed_by_user_id = ?, updated_at = ? WHERE id = ?
        """, (status, confirmed_by_user_id, now_str, decision_id))
    else:
        cursor.execute("""
        UPDATE decisions SET status = ?, updated_at = ? WHERE id = ?
        """, (status, now_str, decision_id))
    conn.commit()
    conn.close()

def search_decisions(workspace_id, channel_id, query_term, include_all_status=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    # If not include_all_status, we only fetch 'confirmed' decisions
    if include_all_status:
        cursor.execute("""
        SELECT * FROM decisions 
        WHERE workspace_id = ? AND channel_id = ? AND (title LIKE ? OR summary LIKE ? OR reason LIKE ?)
        ORDER BY created_at DESC
        """, (workspace_id, channel_id, f"%{query_term}%", f"%{query_term}%", f"%{query_term}%"))
    else:
        cursor.execute("""
        SELECT * FROM decisions 
        WHERE workspace_id = ? AND channel_id = ? AND status = 'confirmed' AND (title LIKE ? OR summary LIKE ? OR reason LIKE ?)
        ORDER BY created_at DESC
        """, (workspace_id, channel_id, f"%{query_term}%", f"%{query_term}%", f"%{query_term}%"))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_active_decisions(workspace_id, channel_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM decisions 
    WHERE workspace_id = ? AND channel_id = ? AND status = 'confirmed'
    ORDER BY created_at DESC
    """, (workspace_id, channel_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# CRUD Helpers for Conflicts
def save_conflict(workspace_id, channel_id, message_ts, conflict_type, severity, new_message_summary, conflicting_memory_id, explanation, status='open'):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO conflicts (
        workspace_id, channel_id, message_ts, conflict_type, severity, new_message_summary, conflicting_memory_id, explanation, status, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workspace_id, channel_id, message_ts, conflict_type, severity, new_message_summary, conflicting_memory_id, explanation, status, now_str
    ))
    conflict_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return conflict_id

def update_conflict_status(conflict_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE conflicts SET status = ? WHERE id = ?
    """, (status, conflict_id))
    conn.commit()
    conn.close()

def get_conflict(conflict_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_active_conflicts(workspace_id, channel_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM conflicts 
    WHERE workspace_id = ? AND channel_id = ? AND status = 'open'
    ORDER BY created_at DESC
    """, (workspace_id, channel_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# CRUD Helpers for Tasks
def save_task(workspace_id, channel_id, title, owner_user_id, status, due_date, evidence_message_ts):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO tasks (
        workspace_id, channel_id, title, owner_user_id, status, due_date, evidence_message_ts, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workspace_id, channel_id, title, owner_user_id, status, due_date, evidence_message_ts, now_str, now_str
    ))
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id

def get_channel_tasks(workspace_id, channel_id, status=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
        SELECT * FROM tasks WHERE workspace_id = ? AND channel_id = ? AND status = ?
        ORDER BY created_at DESC
        """, (workspace_id, channel_id, status))
    else:
        cursor.execute("""
        SELECT * FROM tasks WHERE workspace_id = ? AND channel_id = ?
        ORDER BY created_at DESC
        """, (workspace_id, channel_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# CRUD Helpers for Memory Items
def save_memory_item(workspace_id, channel_id, type_str, title, summary, status, confidence):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO memory_items (
        workspace_id, channel_id, type, title, summary, status, confidence, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workspace_id, channel_id, type_str, title, summary, status, confidence, now_str, now_str
    ))
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return item_id

def get_channel_memory_items(workspace_id, channel_id, type_str=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if type_str:
        cursor.execute("""
        SELECT * FROM memory_items WHERE workspace_id = ? AND channel_id = ? AND type = ?
        ORDER BY created_at DESC
        """, (workspace_id, channel_id, type_str))
    else:
        cursor.execute("""
        SELECT * FROM memory_items WHERE workspace_id = ? AND channel_id = ?
        ORDER BY created_at DESC
        """, (workspace_id, channel_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
