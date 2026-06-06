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

    # --- conflicts ---
    def save_conflict(self, conflict: Record) -> Record: ...

    def update_conflict_status(self, conflict_id: str, status: str) -> Record | None: ...

    # --- evidence ---
    def add_evidence(self, memory_item_id: str, links: list[Record]) -> int:
        """Attach evidence links to a memory item; return count added."""
        ...
