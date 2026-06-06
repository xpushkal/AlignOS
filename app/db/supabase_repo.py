"""Supabase-backed Repository implementation.

Thin wrapper over the `supabase` Python client. Mirrors InMemoryRepository
semantics against the schema in supabase/migrations/0001_init.sql. The `supabase`
package is imported lazily so the app can run without it installed when using the
in-memory backend.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .base import Record, Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseRepository(Repository):
    backend = "supabase"

    def __init__(self, url: str, service_key: str) -> None:
        from supabase import create_client  # lazy import

        self.client = create_client(url, service_key)

    # --- decisions ---
    def save_decision(self, decision: Record) -> Record:
        payload = dict(decision)
        payload.setdefault("id", str(uuid.uuid4()))
        payload.setdefault("status", "confirmed")
        payload.setdefault("created_at", _now())
        payload["updated_at"] = _now()
        self.client.table("decisions").upsert(payload).execute()

        # Mirror into memory_items for unified search/summaries.
        self.client.table("memory_items").upsert(
            {
                "id": payload["id"],
                "workspace_id": payload.get("workspace_id"),
                "channel_id": payload.get("channel_id"),
                "type": "decision",
                "title": payload.get("title", ""),
                "summary": payload.get("summary", ""),
                "status": payload["status"],
                "confidence": payload.get("confidence"),
                "created_at": payload["created_at"],
                "updated_at": payload["updated_at"],
            }
        ).execute()
        return payload

    def get_decision(self, decision_id: str) -> Record | None:
        res = self.client.table("decisions").select("*").eq("id", decision_id).execute()
        return res.data[0] if res.data else None

    def update_decision_status(self, decision_id: str, status: str) -> Record | None:
        res = (
            self.client.table("decisions")
            .update({"status": status, "updated_at": _now()})
            .eq("id", decision_id)
            .execute()
        )
        self.client.table("memory_items").update({"status": status}).eq(
            "id", decision_id
        ).execute()
        return res.data[0] if res.data else None

    # --- memory search ---
    def search_memory(
        self, query: str, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        q = self.client.table("memory_items").select("*").eq("workspace_id", workspace_id)
        if channel_id is not None:
            q = q.eq("channel_id", channel_id)
        if query.strip():
            # trigram-friendly ILIKE on title/summary
            q = q.or_(f"title.ilike.%{query}%,summary.ilike.%{query}%")
        return q.order("created_at", desc=True).execute().data or []

    def list_memory(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        q = self.client.table("memory_items").select("*").eq("workspace_id", workspace_id)
        if channel_id is not None:
            q = q.eq("channel_id", channel_id)
        return q.order("created_at", desc=True).execute().data or []

    # --- conflicts ---
    def save_conflict(self, conflict: Record) -> Record:
        payload = dict(conflict)
        payload.setdefault("id", str(uuid.uuid4()))
        payload.setdefault("status", "open")
        payload.setdefault("created_at", _now())
        self.client.table("conflicts").upsert(payload).execute()
        return payload

    def update_conflict_status(self, conflict_id: str, status: str) -> Record | None:
        res = (
            self.client.table("conflicts")
            .update({"status": status})
            .eq("id", conflict_id)
            .execute()
        )
        return res.data[0] if res.data else None

    # --- evidence ---
    def add_evidence(self, memory_item_id: str, links: list[Record]) -> int:
        rows = []
        for link in links:
            row = dict(link)
            row.setdefault("id", str(uuid.uuid4()))
            row["memory_item_id"] = memory_item_id
            row.setdefault("created_at", _now())
            rows.append(row)
        if rows:
            self.client.table("evidence_links").insert(rows).execute()
        return len(rows)
