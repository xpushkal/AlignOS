"""Neon PostgreSQL Repository implementation (psycopg v3).

Mirrors InMemoryRepository semantics against the schema in
migrations/0001_init.sql. The `psycopg` package is imported lazily so the app can
run on the in-memory backend without it installed.

Neon is serverless Postgres; this opens a short-lived connection per operation
(use the pooled connection string from the Neon dashboard for best results).
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any

from .base import Record, Repository


class PostgresRepository(Repository):
    backend = "neon-postgres"

    def __init__(self, dsn: str) -> None:
        import psycopg  # lazy import
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self._dict_row = dict_row
        self.dsn = dsn

    @contextmanager
    def _cursor(self):
        with self._psycopg.connect(self.dsn, row_factory=self._dict_row) as conn:
            with conn.cursor() as cur:
                yield cur
            conn.commit()

    # --- decisions ---
    def save_decision(self, decision: Record) -> Record:
        with self._cursor() as cur:
            cur.execute(
                """
                insert into decisions
                    (workspace_id, channel_id, thread_ts, title, summary, reason,
                     status, confidence)
                values (%(workspace_id)s, %(channel_id)s, %(thread_ts)s, %(title)s,
                        %(summary)s, %(reason)s,
                        coalesce(%(status)s,'confirmed')::decision_status,
                        %(confidence)s)
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
        sql = "select * from memory_items where workspace_id = %s"
        params: list[Any] = [workspace_id]
        if channel_id is not None:
            sql += " and channel_id = %s"
            params.append(channel_id)
        # Tokenize and match any term against title/summary (parity with the
        # in-memory backend) so "what did we decide about postgresql?" matches.
        tokens = re.findall(r"[a-z0-9]+", query.lower())
        if tokens:
            clauses = " or ".join("(title ilike %s or summary ilike %s)" for _ in tokens)
            sql += f" and ({clauses})"
            for t in tokens:
                params += [f"%{t}%", f"%{t}%"]
        sql += " order by created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

    def list_memory(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        sql = "select * from memory_items where workspace_id = %s"
        params: list[Any] = [workspace_id]
        if channel_id is not None:
            sql += " and channel_id = %s"
            params.append(channel_id)
        sql += " order by created_at desc"
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [_norm(r) for r in cur.fetchall()]

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
            )
        return len(links)


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
