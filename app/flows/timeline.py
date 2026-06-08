"""Decision Timeline flow (Feature 1).

Retrieves confirmed decisions chronologically and presents them with dates, titles, reasons, and evidence.
"""
from __future__ import annotations

from typing import Any
from app import mcp_client


async def get_timeline(workspace_id: str, channel_id: str | None = None) -> dict[str, Any]:
    """Retrieve decision timeline for the channel."""
    return await mcp_client.call_tool(
        "get_decision_timeline",
        {"workspace_id": workspace_id, "channel_id": channel_id},
    )
