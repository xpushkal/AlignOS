"""In-memory Repository implementation.

Zero external dependencies. Used for local dev, tests, and the demo harness when
Supabase is not configured. Data lives only for the process lifetime.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .base import Record, Repository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class InMemoryRepository(Repository):
    backend = "in-memory"

    def __init__(self) -> None:
        self._decisions: dict[str, Record] = {}
        self._memory_items: dict[str, Record] = {}
        self._conflicts: dict[str, Record] = {}
        self._evidence: dict[str, list[Record]] = {}

    # --- decisions ---
    def save_decision(self, decision: Record) -> Record:
        record = dict(decision)
        record.setdefault("id", _new_id())
        record.setdefault("status", "confirmed")
        record.setdefault("created_at", _now())
        record["updated_at"] = _now()
        self._decisions[record["id"]] = record

        # Mirror into the unified memory_items surface so search/summary see it.
        self._memory_items[record["id"]] = {
            "id": record["id"],
            "workspace_id": record.get("workspace_id"),
            "channel_id": record.get("channel_id"),
            "type": "decision",
            "title": record.get("title", ""),
            "summary": record.get("summary", ""),
            "status": record["status"],
            "confidence": record.get("confidence"),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }
        return record

    def get_decision(self, decision_id: str) -> Record | None:
        return self._decisions.get(decision_id)

    def update_decision_status(self, decision_id: str, status: str) -> Record | None:
        record = self._decisions.get(decision_id)
        if not record:
            return None
        record["status"] = status
        record["updated_at"] = _now()
        if decision_id in self._memory_items:
            self._memory_items[decision_id]["status"] = status
        return record

    # --- memory search ---
    def search_memory(
        self, query: str, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        terms = [t for t in query.lower().split() if t]
        results = []
        for item in self.list_memory(workspace_id, channel_id):
            haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
            if not terms or any(t in haystack for t in terms):
                results.append(item)
        return results

    def list_memory(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        items = [
            i for i in self._memory_items.values() if i.get("workspace_id") == workspace_id
        ]
        if channel_id is not None:
            items = [i for i in items if i.get("channel_id") == channel_id]
        return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)

    # --- conflicts ---
    def save_conflict(self, conflict: Record) -> Record:
        record = dict(conflict)
        record.setdefault("id", _new_id())
        record.setdefault("status", "open")
        record.setdefault("created_at", _now())
        self._conflicts[record["id"]] = record
        return record

    def update_conflict_status(self, conflict_id: str, status: str) -> Record | None:
        record = self._conflicts.get(conflict_id)
        if not record:
            return None
        record["status"] = status
        return record

    # --- evidence ---
    def add_evidence(self, memory_item_id: str, links: list[Record]) -> int:
        bucket = self._evidence.setdefault(memory_item_id, [])
        for link in links:
            row = dict(link)
            row.setdefault("id", _new_id())
            row["memory_item_id"] = memory_item_id
            row.setdefault("created_at", _now())
            bucket.append(row)
        if memory_item_id in self._decisions:
            self._decisions[memory_item_id]["evidence_count"] = len(bucket)
        return len(links)
