"""Project Health flow (Feature 7).

Aggregates open tasks, blockers, conflicts, deadlines, and calculates status (Green/Yellow/Red).
"""
from __future__ import annotations

from typing import Any
from app import mcp_client


async def get_health_summary(workspace_id: str, channel_id: str | None = None) -> dict[str, Any]:
    """Fetch project health scan statistics."""
    return await mcp_client.call_tool(
        "get_project_health",
        {"workspace_id": workspace_id, "channel_id": channel_id},
    )
