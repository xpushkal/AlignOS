"""In-memory Repository implementation.

Zero external dependencies. Used for local dev, tests, and the demo harness when
no database (DATABASE_URL) is configured. Data lives only for the process lifetime.
"""
from __future__ import annotations

import re
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
        # Tokenize on word chars so punctuation (e.g. "postgresql?") still matches.
        terms = re.findall(r"[a-z0-9]+", query.lower())
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
            dict(i) for i in self._memory_items.values() if i.get("workspace_id") == workspace_id
        ]
        if channel_id is not None:
            items = [i for i in items if i.get("channel_id") == channel_id]
        for item in items:
            if item.get("type") == "decision":
                dec = self._decisions.get(item["id"])
                if dec:
                    item["reason"] = dec.get("reason", "")
        return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)

    def list_decisions(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        items = [
            i for i in self._decisions.values() if i.get("workspace_id") == workspace_id
        ]
        if channel_id is not None:
            items = [i for i in items if i.get("channel_id") == channel_id]
        return sorted(items, key=lambda i: i.get("created_at", ""))

    def list_tasks(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        self._tasks = getattr(self, "_tasks", {})
        items = [
            i for i in self._tasks.values() if i.get("workspace_id") == workspace_id
        ]
        if channel_id is not None:
            items = [i for i in items if i.get("channel_id") == channel_id]
        return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)

    def list_blockers(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        self._blockers = getattr(self, "_blockers", {})
        items = [
            i for i in self._blockers.values() if i.get("workspace_id") == workspace_id
        ]
        if channel_id is not None:
            items = [i for i in items if i.get("channel_id") == channel_id]
        return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)

    # --- tasks & blockers ---

    def save_task(self, task: Record) -> Record:
        record = dict(task)
        record.setdefault("id", _new_id())
        record.setdefault("status", "open")
        record.setdefault("created_at", _now())
        record["updated_at"] = _now()
        self._tasks = getattr(self, "_tasks", {})
        self._tasks[record["id"]] = record

        # Mirror into unified memory
        self._memory_items[record["id"]] = {
            "id": record["id"],
            "workspace_id": record.get("workspace_id"),
            "channel_id": record.get("channel_id"),
            "type": "task",
            "title": record.get("title", ""),
            "summary": f"Owner: {record.get('owner_user_id') or 'unassigned'}, Due: {record.get('due_date') or 'none'}",
            "status": record["status"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }
        return record

    def update_task_status(self, task_id: str, status: str) -> Record | None:
        self._tasks = getattr(self, "_tasks", {})
        record = self._tasks.get(task_id)
        if not record:
            return None
        record["status"] = status
        record["updated_at"] = _now()
        if task_id in self._memory_items:
            self._memory_items[task_id]["status"] = status
        return record

    def save_blocker(self, blocker: Record) -> Record:
        record = dict(blocker)
        record.setdefault("id", _new_id())
        record.setdefault("status", "open")
        record.setdefault("created_at", _now())
        record["updated_at"] = _now()
        self._blockers = getattr(self, "_blockers", {})
        self._blockers[record["id"]] = record

        # Mirror into unified memory
        self._memory_items[record["id"]] = {
            "id": record["id"],
            "workspace_id": record.get("workspace_id"),
            "channel_id": record.get("channel_id"),
            "type": "blocker",
            "title": record.get("title", ""),
            "summary": record.get("description") or "",
            "status": record["status"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }
        return record

    def update_blocker_status(self, blocker_id: str, status: str) -> Record | None:
        self._blockers = getattr(self, "_blockers", {})
        record = self._blockers.get(blocker_id)
        if not record:
            return None
        record["status"] = status
        record["updated_at"] = _now()
        if blocker_id in self._memory_items:
            self._memory_items[blocker_id]["status"] = status
        return record

    # --- reminders ---
    def save_reminder(self, reminder: Record) -> Record:
        record = dict(reminder)
        record.setdefault("id", _new_id())
        record.setdefault("status", "scheduled")
        record.setdefault("created_at", _now())
        self._reminders = getattr(self, "_reminders", {})
        self._reminders[record["id"]] = record
        return record

    def get_pending_reminders(self) -> list[Record]:
        self._reminders = getattr(self, "_reminders", {})
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        results = []
        for r in self._reminders.values():
            rem_time = r.get("remind_at")
            if isinstance(rem_time, str):
                try:
                    rem_time = datetime.datetime.fromisoformat(rem_time.replace("Z", "+00:00"))
                except Exception:
                    continue
            if r.get("status") == "scheduled" and rem_time and rem_time <= now:
                results.append(r)
        return results


    def update_reminder_status(self, reminder_id: str, status: str) -> Record | None:
        self._reminders = getattr(self, "_reminders", {})
        record = self._reminders.get(reminder_id)
        if not record:
            return None
        record["status"] = status
        return record

    # --- cleanup actions ---
    def execute_cleanup_action(
        self, action: str, item_id: str, target_id: str | None = None
    ) -> Record | None:
        mitem = self._memory_items.get(item_id)
        if not mitem:
            return None
        itype = mitem["type"]

        if action == "delete":
            self._memory_items.pop(item_id, None)
            if itype == "decision":
                self._decisions.pop(item_id, None)
            elif itype == "task":
                getattr(self, "_tasks", {}).pop(item_id, None)
            elif itype == "blocker":
                getattr(self, "_blockers", {}).pop(item_id, None)
            return {"id": item_id, "action": "deleted"}

        elif action == "archive":
            mitem["status"] = "archived"
            if itype == "decision":
                if item_id in self._decisions:
                    self._decisions[item_id]["status"] = "archived"
            elif itype == "task":
                tasks = getattr(self, "_tasks", {})
                if item_id in tasks:
                    tasks[item_id]["status"] = "archived"
            elif itype == "blocker":
                blockers = getattr(self, "_blockers", {})
                if item_id in blockers:
                    blockers[item_id]["status"] = "archived"
            return {"id": item_id, "action": "archived"}

        elif action == "supersede":
            if itype == "decision":
                mitem["status"] = "superseded"
                if item_id in self._decisions:
                    self._decisions[item_id]["status"] = "superseded"
                    self._decisions[item_id]["supersedes_decision_id"] = target_id
                return {"id": item_id, "action": "superseded"}

        elif action == "merge":
            if itype == "task":
                self._memory_items.pop(target_id, None)
                getattr(self, "_tasks", {}).pop(target_id, None)
                return {"id": item_id, "merged_id": target_id, "action": "merged"}

        elif action == "ignore":
            return {"id": item_id, "action": "ignored"}

        return None

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

    def list_conflicts(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        items = [
            i for i in self._conflicts.values() if i.get("workspace_id") == workspace_id
        ]
        if channel_id is not None:
            items = [i for i in items if i.get("channel_id") == channel_id]
        return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)


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

    def get_evidence(self, memory_item_id: str) -> list[Record]:
        return self._evidence.get(memory_item_id, [])


