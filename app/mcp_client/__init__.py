"""MCP client wrapper.

The backend calls AlignOS tools through `call_tool`. For the MVP and tests this
invokes the in-process implementations in `mcp_server.core` directly (the
documented "local fallback" path). The seam is intentional: a future version can
spawn the MCP stdio server and route the same calls over the protocol without
changing any caller.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp_server import core

logger = logging.getLogger("alignos.mcp_client")


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke an MCP tool by name and return its parsed result dict."""
    try:
        return core.call(name, arguments)
    except KeyError:
        logger.error("Unknown MCP tool requested: %s", name)
        raise
    except Exception as exc:  # graceful: MCP failures must not crash the app
        logger.exception("MCP tool '%s' failed: %s", name, exc)
        return {"error": str(exc), "tool": name}


def available_tools() -> list[str]:
    return list(core.TOOL_NAMES)
