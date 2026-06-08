"""Neon PostgreSQL Repository implementation (psycopg v3).

Mirrors InMemoryRepository semantics against the schema in
migrations/0001_init.sql. The `psycopg` packages are imported lazily so the app
can run on the in-memory backend without them installed.

Uses a connection pool so we don't pay the (~2s) TLS+handshake cost of a fresh
Neon connection on every query. Connections are reused and liveness-checked
before hand-out, so an idle connection closed by Neon is transparently replaced.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any

from .base import Record, Repository


class PostgresRepository(Repository):
    backend = "neon-postgres"

    def __init__(self, dsn: str) -> None:
        from psycopg.rows import dict_row  # lazy import
        from psycopg_pool import ConnectionPool

        from app.config import get_settings

        self.dsn = dsn
        self._pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=max(4, get_settings().db_pool_max_size),
            open=True,
            # Reset/ping a connection before handing it out so a stale one
            # (closed by Neon while idle) is recycled instead of erroring.
            check=ConnectionPool.check_connection,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )

    @contextmanager
    def _cursor(self):
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                yield cur

    # --- decisions ---
    def save_decision(self, decision: Record) -> Record:
        with self._cursor() as cur:
            cur.execute(
                """
                insert into decisions
                    (workspace_id, channel_id, thread_ts, title, summary, reason,
                     status, confidence, confirmed_by_user_id)
                values (%(workspace_id)s, %(channel_id)s, %(thread_ts)s, %(title)s,
                        %(summary)s, %(reason)s,
                        coalesce(%(status)s,'confirmed')::decision_status,
                        %(confidence)s, %(confirmed_by_user_id)s)
                returning *
                """,
                {
                    "workspace_id": decision.get("workspace_id"),
                    "channel_id": decision.get("channel_id"),
                    "thread_ts": decision.get("thread_ts"),
                    "title": decision.get("title", ""),
                    "summary": decision.get("summary", ""),
                    "reason": decision.get("reason", ""),
                    "status": decision.get("status"),
                    "confidence": decision.get("confidence"),
                    "confirmed_by_user_id": decision.get("confirmed_by_user_id"),
                },
            )
            row = cur.fetchone()
            # Mirror into memory_items using the same id for unified search.
            cur.execute(
                """
                insert into memory_items
                    (id, workspace_id, channel_id, type, title, summary, status, confidence)
                values (%(id)s, %(workspace_id)s, %(channel_id)s, 'decision',
                        %(title)s, %(summary)s, %(status)s, %(confidence)s)
                on conflict (id) do update set
                    title = excluded.title, summary = excluded.summary,
                    status = excluded.status, updated_at = now()
                """,
                {
                    "id": row["id"],
                    "workspace_id": row["workspace_id"],
                    "channel_id": row["channel_id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "status": row["status"],
                    "confidence": row["confidence"],
                },
            )
        return {"id": str(row["id"]), "status": row["status"], **_strip_ids(row)}

    def get_decision(self, decision_id: str) -> Record | None:
        with self._cursor() as cur:
            cur.execute("select * from decisions where id = %s", (decision_id,))
            row = cur.fetchone()
        return _norm(row) if row else None

    def update_decision_status(self, decision_id: str, status: str) -> Record | None:
        with self._cursor() as cur:
            cur.execute(
                "update decisions set status = %s::decision_status, updated_at = now() "
                "where id = %s returning *",
                (status, decision_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "update memory_items set status = %s, updated_at = now() where id = %s",
                    (status, decision_id),
                )
        return _norm(row) if row else None

    # --- memory search ---
    def search_memory(
        self, query: str, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = """
            select m.*, d.reason 
            from memory_items m 
            left join decisions d on m.id = d.id 
            where m.workspace_id = %s
        """
        params: list[Any] = [workspace_id]
        if channel_id is not None:
            sql += " and m.channel_id = %s"
            params.append(channel_id)
        # Tokenize and match any term against title/summary (parity with the
        # in-memory backend) so "what did we decide about postgresql?" matches.
        tokens = re.findall(r"[a-z0-9]+", query.lower())
        if tokens:
            clauses = " or ".join("(m.title ilike %s or m.summary ilike %s)" for _ in tokens)
            sql += f" and ({clauses})"
            for t in tokens:
                params += [f"%{t}%", f"%{t}%"]
        sql += " order by m.created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

    def list_memory(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = """
            select m.*, d.reason 
            from memory_items m 
            left join decisions d on m.id = d.id 
            where m.workspace_id = %s
        """
        params: list[Any] = [workspace_id]
        if channel_id is not None:
            sql += " and m.channel_id = %s"
            params.append(channel_id)
        sql += " order by m.created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

    def list_decisions(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = "select * from decisions where workspace_id = %s"
        params = [workspace_id]
        if channel_id is not None:
            sql += " and channel_id = %s"
            params.append(channel_id)
        sql += " order by created_at asc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

    def list_tasks(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = "select * from tasks where workspace_id = %s"
        params = [workspace_id]
        if channel_id is not None:
            sql += " and channel_id = %s"
            params.append(channel_id)
        sql += " order by created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

    def list_blockers(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = "select * from blockers where workspace_id = %s"
        params = [workspace_id]
        if channel_id is not None:
            sql += " and channel_id = %s"
            params.append(channel_id)
        sql += " order by created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

    # --- tasks & blockers ---

    def save_task(self, task: Record) -> Record:
        with self._cursor() as cur:
            cur.execute(
                """
                insert into tasks
                    (workspace_id, channel_id, title, owner_user_id, status, due_date, evidence_message_ts)
                values (%(workspace_id)s, %(channel_id)s, %(title)s, %(owner_user_id)s,
                        coalesce(%(status)s,'open')::task_status, %(due_date)s, %(evidence_message_ts)s)
                returning *
                """,
                {
                    "workspace_id": task.get("workspace_id"),
                    "channel_id": task.get("channel_id"),
                    "title": task.get("title", ""),
                    "owner_user_id": task.get("owner_user_id"),
                    "status": task.get("status"),
                    "due_date": task.get("due_date"),
                    "evidence_message_ts": task.get("evidence_message_ts"),
                },
            )
            row = cur.fetchone()
            # Mirror to memory_items
            cur.execute(
                """
                insert into memory_items
                    (id, workspace_id, channel_id, type, title, summary, status)
                values (%(id)s, %(workspace_id)s, %(channel_id)s, 'task',
                        %(title)s, %(summary)s, %(status)s)
                on conflict (id) do update set
                    title = excluded.title, summary = excluded.summary, status = excluded.status, updated_at = now()
                """,
                {
                    "id": row["id"],
                    "workspace_id": row["workspace_id"],
                    "channel_id": row["channel_id"],
                    "title": row["title"],
                    "summary": f"Owner: {row['owner_user_id'] or 'unassigned'}, Due: {row['due_date'] or 'none'}",
                    "status": row["status"],
                },
            )
        return {"id": str(row["id"]), "status": row["status"], **_strip_ids(row)}

    def update_task_status(self, task_id: str, status: str) -> Record | None:
        with self._cursor() as cur:
            cur.execute(
                "update tasks set status = %s::task_status, updated_at = now() where id = %s returning *",
                (status, task_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "update memory_items set status = %s, updated_at = now() where id = %s",
                    (status, task_id),
                )
        return _norm(row) if row else None

    def save_blocker(self, blocker: Record) -> Record:
        with self._cursor() as cur:
            cur.execute(
                """
                insert into blockers
                    (workspace_id, channel_id, title, description, status, evidence_message_ts)
                values (%(workspace_id)s, %(channel_id)s, %(title)s, %(description)s,
                        coalesce(%(status)s,'open')::blocker_status, %(evidence_message_ts)s)
                returning *
                """,
                {
                    "workspace_id": blocker.get("workspace_id"),
                    "channel_id": blocker.get("channel_id"),
                    "title": blocker.get("title", ""),
                    "description": blocker.get("description"),
                    "status": blocker.get("status"),
                    "evidence_message_ts": blocker.get("evidence_message_ts"),
                },
            )
            row = cur.fetchone()
            # Mirror to memory_items
            cur.execute(
                """
                insert into memory_items
                    (id, workspace_id, channel_id, type, title, summary, status)
                values (%(id)s, %(workspace_id)s, %(channel_id)s, 'blocker',
                        %(title)s, %(summary)s, %(status)s)
                on conflict (id) do update set
                    title = excluded.title, summary = excluded.summary, status = excluded.status, updated_at = now()
                """,
                {
                    "id": row["id"],
                    "workspace_id": row["workspace_id"],
                    "channel_id": row["channel_id"],
                    "title": row["title"],
                    "summary": row["description"] or "",
                    "status": row["status"],
                },
            )
        return {"id": str(row["id"]), "status": row["status"], **_strip_ids(row)}

    def update_blocker_status(self, blocker_id: str, status: str) -> Record | None:
        with self._cursor() as cur:
            cur.execute(
                "update blockers set status = %s::blocker_status, updated_at = now() where id = %s returning *",
                (status, blocker_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "update memory_items set status = %s, updated_at = now() where id = %s",
                    (status, blocker_id),
                )
        return _norm(row) if row else None

    # --- reminders ---
    def save_reminder(self, reminder: Record) -> Record:
        with self._cursor() as cur:
            cur.execute(
                """
                insert into reminders
                    (workspace_id, task_id, owner_slack_id, task_title, deadline, remind_at, status)
                values (%(workspace_id)s, %(task_id)s, %(owner_slack_id)s, %(task_title)s,
                        %(deadline)s, %(remind_at)s, coalesce(%(status)s,'scheduled'))
                returning *
                """,
                {
                    "workspace_id": reminder.get("workspace_id"),
                    "task_id": reminder.get("task_id"),
                    "owner_slack_id": reminder.get("owner_slack_id"),
                    "task_title": reminder.get("task_title", ""),
                    "deadline": reminder.get("deadline"),
                    "remind_at": reminder.get("remind_at"),
                    "status": reminder.get("status"),
                },
            )
            row = cur.fetchone()
        return _norm(row)

    def get_pending_reminders(self) -> list[Record]:
        with self._cursor() as cur:
            cur.execute(
                "select * from reminders where status = 'scheduled' and remind_at <= now()"
            )
            return [_norm(r) for r in cur.fetchall()]

    def update_reminder_status(self, reminder_id: str, status: str) -> Record | None:
        with self._cursor() as cur:
            cur.execute(
                "update reminders set status = %s where id = %s returning *",
                (status, reminder_id),
            )
            row = cur.fetchone()
        return _norm(row) if row else None

    # --- cleanup actions ---
    def execute_cleanup_action(
        self, action: str, item_id: str, target_id: str | None = None
    ) -> Record | None:
        with self._cursor() as cur:
            # First figure out type of item from memory_items
            cur.execute("select type from memory_items where id = %s", (item_id,))
            mem_row = cur.fetchone()
            if not mem_row:
                return None
            itype = mem_row["type"]

            if action == "delete":
                if itype == "decision":
                    cur.execute("delete from decisions where id = %s", (item_id,))
                elif itype == "task":
                    cur.execute("delete from tasks where id = %s", (item_id,))
                elif itype == "blocker":
                    cur.execute("delete from blockers where id = %s", (item_id,))
                cur.execute("delete from memory_items where id = %s", (item_id,))
                return {"id": item_id, "action": "deleted"}

            elif action == "archive":
                if itype == "decision":
                    cur.execute("update decisions set status = 'archived'::decision_status where id = %s", (item_id,))
                elif itype == "task":
                    cur.execute("update tasks set status = 'archived'::task_status where id = %s", (item_id,))
                elif itype == "blocker":
                    cur.execute("update blockers set status = 'archived'::blocker_status where id = %s", (item_id,))
                cur.execute("update memory_items set status = 'archived' where id = %s", (item_id,))
                return {"id": item_id, "action": "archived"}

            elif action == "supersede":
                if itype == "decision":
                    cur.execute(
                        "update decisions set status = 'superseded'::decision_status, supersedes_decision_id = %s where id = %s",
                        (target_id, item_id),
                    )
                    cur.execute("update memory_items set status = 'superseded' where id = %s", (item_id,))
                    return {"id": item_id, "action": "superseded"}

            elif action == "merge":
                if itype == "task":
                    cur.execute("delete from tasks where id = %s", (target_id,))
                    cur.execute("delete from memory_items where id = %s", (target_id,))
                    return {"id": item_id, "merged_id": target_id, "action": "merged"}

            elif action == "ignore":
                cur.execute(
                    "insert into audit_events (workspace_id, event_type, target_id, metadata) values ('global', 'cleanup_ignore', %s, '{\"status\": \"ignored\"}')",
                    (item_id,),
                )
                return {"id": item_id, "action": "ignored"}
            return None


    # --- conflicts ---
    def save_conflict(self, conflict: Record) -> Record:
        with self._cursor() as cur:
            cur.execute(
                """
                insert into conflicts
                    (workspace_id, channel_id, message_ts, conflict_type, severity,
                     new_message_summary, conflicting_memory_id, explanation, status)
                values (%(workspace_id)s, %(channel_id)s, %(message_ts)s,
                        %(conflict_type)s, %(severity)s, %(new_message_summary)s,
                        %(conflicting_memory_id)s, %(explanation)s,
                        coalesce(%(status)s,'open')::conflict_status)
                returning *
                """,
                {
                    "workspace_id": conflict.get("workspace_id"),
                    "channel_id": conflict.get("channel_id"),
                    "message_ts": conflict.get("message_ts"),
                    "conflict_type": conflict.get("conflict_type"),
                    "severity": conflict.get("severity"),
                    "new_message_summary": conflict.get("new_message_summary"),
                    "conflicting_memory_id": conflict.get("conflicting_memory_id"),
                    "explanation": conflict.get("explanation"),
                    "status": conflict.get("status"),
                },
            )
            row = cur.fetchone()
        return _norm(row)

    def update_conflict_status(self, conflict_id: str, status: str) -> Record | None:
        with self._cursor() as cur:
            cur.execute(
                "update conflicts set status = %s::conflict_status where id = %s returning *",
                (status, conflict_id),
            )
            row = cur.fetchone()
        return _norm(row) if row else None

    def list_conflicts(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = "select * from conflicts where workspace_id = %s"
        params = [workspace_id]
        if channel_id is not None:
            sql += " and channel_id = %s"
            params.append(channel_id)
        sql += " order by created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]


    # --- evidence ---
    def add_evidence(self, memory_item_id: str, links: list[Record]) -> int:
        if not links:
            return 0
        with self._cursor() as cur:
            for link in links:
                cur.execute(
                    """
                    insert into evidence_links
                        (memory_item_id, source_type, slack_channel_id,
                         slack_message_ts, slack_thread_ts, slack_user_id, snippet)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        memory_item_id,
                        link.get("source_type", "slack_message"),
                        link.get("slack_channel_id"),
                        link.get("slack_message_ts"),
                        link.get("slack_thread_ts"),
                        link.get("slack_user_id"),
                        link.get("snippet"),
                    ),
                )
            cur.execute(
                "update decisions set evidence_count = evidence_count + %s where id = %s",
                (len(links), memory_item_id),
        return len(links)

    def get_evidence(self, memory_item_id: str) -> list[Record]:
        with self._cursor() as cur:
            cur.execute("select * from evidence_links where memory_item_id = %s", (memory_item_id,))
            return [_norm(r) for r in cur.fetchall()]



def _norm(row: Record | None) -> Record:
    """Convert DB values to JSON-friendly types (uuid/datetime->str, Decimal->float)."""
    if row is None:
        return {}
    return {k: _conv(v) for k, v in row.items()}


def _strip_ids(row: Record) -> Record:
    return {k: _conv(v) for k, v in row.items() if k not in ("id", "status")}


def _conv(value: Any) -> Any:
    import datetime
    import decimal
    import uuid

    if isinstance(value, (uuid.UUID, datetime.date, datetime.datetime)):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value
