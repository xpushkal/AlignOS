"""PRD Impact Detection flow (Feature 8).

Analyzes decisions for product scope impact, generates suggested updates, and writes them to Docs/prd.md on confirmation.
"""
from __future__ import annotations

import os
from typing import Any
from app import mcp_client
from app.concurrency import run_blocking


async def get_prd_suggestions(decision_id: str, workspace_id: str) -> dict[str, Any]:
    """Get suggested requirements modifications for a confirmed decision."""
    return await mcp_client.call_tool(
        "generate_prd_suggestions",
        {"decision_id": decision_id, "workspace_id": workspace_id},
    )


async def apply_prd_suggestions(suggestions: list[dict[str, Any]], prd_path: str = "") -> bool:
    """Append approved requirement updates to Docs/prd.md."""
    if not prd_path:
        # Resolve path to Docs/prd.md relative to project root
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prd_path = os.path.join(base_dir, "Docs", "prd.md")

    if not os.path.exists(prd_path):
        return False

    def write_append():
        with open(prd_path, "a", encoding="utf-8") as f:
            f.write("\n\n---\n\n## Approved Requirements Updates\n")
            for sug in suggestions:
                sect = sug.get("section_to_update", "General")
                req = sug.get("proposed_requirement_text", "")
                criteria = "\n".join(f"- {c}" for c in sug.get("acceptance_criteria", []))
                reason = sug.get("reason_for_update", "")
                
                f.write(
                    f"\n### Section: {sect}\n"
                    f"* **Proposed Requirement:** {req}\n"
                    f"* **Acceptance Criteria:**\n{criteria}\n"
                    f"* **Rationale:** {reason}\n"
                )
        return True

    return await run_blocking(write_append)
