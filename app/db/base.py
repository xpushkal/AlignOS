"""Repository protocol — the storage contract used by the MCP tools and flows."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# Memory records are passed around as plain dicts to keep the storage layer
# decoupled from any ORM. Keys mirror the columns in Docs/DATA_MODEL.md.
Record = dict[str, Any]


@runtime_checkable
class Repository(Protocol):
    backend: str

    # --- decisions ---
    def save_decision(self, decision: Record) -> Record:
        """Persist a decision (status 'confirmed' by default) and return the row."""
        ...

    def get_decision(self, decision_id: str) -> Record | None: ...

    def update_decision_status(self, decision_id: str, status: str) -> Record | None:
        """Set a decision's status (e.g. 'reopened', 'superseded')."""
        ...

    def list_tasks(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        """All task records for a workspace/channel."""
        ...

    def list_blockers(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        """All blocker records for a workspace/channel."""
        ...


    # --- memory search ---
    def search_memory(
        self, query: str, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        """Return memory items whose title/summary match the query, scoped."""
        ...

    def list_memory(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        """All memory items for a workspace/channel (for summaries)."""
        ...

    def list_decisions(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        """All decision records for a workspace/channel."""
        ...

    # --- tasks & blockers ---
    def save_task(self, task: Record) -> Record:
        """Persist a task (status 'open' by default) and return the row."""
        ...

    def update_task_status(self, task_id: str, status: str) -> Record | None:
        """Set a task's status."""
        ...

    def save_blocker(self, blocker: Record) -> Record:
        """Persist a blocker (status 'open' by default) and return the row."""
        ...

    def update_blocker_status(self, blocker_id: str, status: str) -> Record | None:
        """Set a blocker's status."""
        ...

    # --- reminders ---
    def save_reminder(self, reminder: Record) -> Record:
        """Schedule a personal deadline reminder."""
        ...

    def get_pending_reminders(self) -> list[Record]:
        """Fetch all reminders in 'scheduled' status that are due."""
        ...

    def update_reminder_status(self, reminder_id: str, status: str) -> Record | None:
        """Update a reminder's status."""
        ...

    # --- cleanup actions ---
    def execute_cleanup_action(
        self, action: str, item_id: str, target_id: str | None = None
    ) -> Record | None:
        """Execute a cleanup action (delete, archive, supersede, merge, ignore)."""
        ...

    # --- conflicts ---
    def save_conflict(self, conflict: Record) -> Record: ...

    def update_conflict_status(self, conflict_id: str, status: str) -> Record | None: ...

    # --- evidence ---
    def add_evidence(self, memory_item_id: str, links: list[Record]) -> int:
        """Attach evidence links to a memory item; return count added."""
        ...

    def get_evidence(self, memory_item_id: str) -> list[Record]:
        """Fetch all evidence links for a memory item."""
        ...

    def list_conflicts(
        self, workspace_id: str, channel_id: str | None = None
    ) -> list[Record]:
        """All conflict records for a workspace/channel."""
        ...



