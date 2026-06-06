"""Project-memory summary flow (PRD §9.5)."""
from __future__ import annotations

from typing import Any

from app import mcp_client


async def project_summary(
    workspace_id: str, channel_id: str | None = None
) -> dict[str, Any]:
    """Return a structured, skimmable project memory summary."""
    return await mcp_client.call_tool(
        "generate_project_summary",
        {"workspace_id": workspace_id, "channel_id": channel_id},
    )
