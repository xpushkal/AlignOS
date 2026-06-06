"""AlignOS MCP server (stdio transport).

Exposes the 8 tools from `mcp_server.core` over the Model Context Protocol so the
FastAPI backend can connect as an MCP client. Run with:

    python -m mcp_server

The `mcp` package is imported lazily inside `main()` so the rest of the project
imports cleanly even when `mcp` is not installed (the backend then uses the local
fallback in app.mcp_client).
"""
from __future__ import annotations

import json

from . import core


def build_server():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("alignos")

    @server.tool()
    def detect_decision(
        message: str, thread_context: str = "", recent_channel_context: str = ""
    ) -> str:
        """Detect whether a Slack message constitutes a team decision."""
        return json.dumps(core.detect_decision(message, thread_context, recent_channel_context))

    @server.tool()
    def save_decision(
        decision: dict, workspace_id: str, channel_id: str = "", confirmed_by: str = ""
    ) -> str:
        """Persist a confirmed decision and its evidence."""
        return json.dumps(core.save_decision(decision, workspace_id, channel_id or None, confirmed_by or None))

    @server.tool()
    def search_memory(query: str, workspace_id: str, channel_id: str = "") -> str:
        """Search confirmed memory items by topic, scoped to workspace/channel."""
        return json.dumps(core.search_memory(query, workspace_id, channel_id or None))

    @server.tool()
    def detect_conflict(
        new_message: str, relevant_memory: list | None = None, recent_context: str = ""
    ) -> str:
        """Compare a new message against confirmed memory for contradictions."""
        return json.dumps(core.detect_conflict(new_message, relevant_memory, recent_context))

    @server.tool()
    def verify_evidence(
        proposed_answer: str,
        evidence_messages: list | None = None,
        memory_items: list | None = None,
    ) -> str:
        """Check whether a proposed answer is supported by evidence/memory."""
        return json.dumps(core.verify_evidence(proposed_answer, evidence_messages, memory_items))

    @server.tool()
    def generate_project_summary(workspace_id: str, channel_id: str = "") -> str:
        """Produce a skimmable project memory summary."""
        return json.dumps(core.generate_project_summary(workspace_id, channel_id or None))

    @server.tool()
    def reopen_decision(decision_id: str, workspace_id: str, requested_by: str = "") -> str:
        """Move a confirmed decision to 'reopened'."""
        return json.dumps(core.reopen_decision(decision_id, workspace_id, requested_by or None))

    @server.tool()
    def log_conflict_action(conflict_id: str, action: str, actor_user_id: str = "") -> str:
        """Record the user's choice on a conflict alert (remind/reopen/ignore)."""
        return json.dumps(core.log_conflict_action(conflict_id, action, actor_user_id or None))

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
