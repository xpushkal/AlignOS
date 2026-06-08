"""Memory Cleanup flow (Feature 4).

Generates hygiene recommendations for stale decisions, duplicate tasks, completed tasks, and low confidence items, and executes action decisions.
"""
from __future__ import annotations

from typing import Any
from app import mcp_client


async def get_cleanup_suggestions(workspace_id: str, channel_id: str | None = None) -> dict[str, Any]:
    """Retrieve suggestions for stale, duplicate, or rejected memory items."""
    return await mcp_client.call_tool(
        "get_cleanup_suggestions",
        {"workspace_id": workspace_id, "channel_id": channel_id},
    )


async def execute_action(action: str, item_id: str, target_id: str | None = None) -> dict[str, Any]:
    """Execute cleanup actions (delete/archive/supersede/merge/ignore)."""
    return await mcp_client.call_tool(
        "execute_cleanup_action",
        {"action": action, "item_id": item_id, "target_id": target_id},
    )
