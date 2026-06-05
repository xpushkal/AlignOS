import os
import json
import logging
from mcp.server.fastmcp import FastMCP
import database as db
from llm_client import LLMClient

# Configure logging to a file to avoid messing with stdout (stdio transport uses stdout for JSON-RPC)
log_file = os.environ.get("MCP_LOG_FILE", "mcp_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename=log_file,
    filemode="a"
)
logger = logging.getLogger("AlignOS_MCP")

# Initialize FastMCP server
mcp = FastMCP("AlignOS-Memory-Server")

# Initialize LLM client (will use OpenRouter API or fallback to Mock Mode)
llm = LLMClient()

# Ensure database is initialized
db.init_db()

@mcp.tool()
def detect_decision(message: str, thread_context: str = "", recent_context: str = "") -> str:
    """
    Analyze a message and context to detect if a decision was made.
    Returns a JSON string containing the decision details (is_decision, title, summary, reason, participants, confidence).
    """
    logger.info(f"Running detect_decision on message: {message}")
    context = thread_context or recent_context
    try:
        result = llm.detect_decision(message, context)
        return json.dumps(result)
    except Exception as e:
        logger.error(f"Error in detect_decision tool: {e}")
        return json.dumps({"error": str(e), "is_decision": False})

@mcp.tool()
def save_decision(
    workspace_id: str,
    channel_id: str,
    thread_ts: str,
    title: str,
    summary: str,
    reason: str,
    status: str,
    confidence: float,
    evidence_list_json: str = "[]",
    supersedes_decision_id: int = None
) -> str:
    """
    Save a proposed or confirmed decision to the SQLite database.
    evidence_list_json should be a JSON array of dicts containing slack_message_ts, slack_thread_ts, slack_user_id, snippet.
    Returns JSON string with saved decision ID.
    """
    logger.info(f"Running save_decision: {title} (status: {status})")
    try:
        evidence_list = json.loads(evidence_list_json)
        decision_id = db.save_decision(
            workspace_id=workspace_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            title=title,
            summary=summary,
            reason=reason,
            status=status,
            confidence=confidence,
            evidence_list=evidence_list,
            supersedes_decision_id=supersedes_decision_id
        )
        return json.dumps({"status": "success", "decision_id": decision_id})
    except Exception as e:
        logger.error(f"Error in save_decision tool: {e}")
        return json.dumps({"status": "error", "error": str(e)})

@mcp.tool()
def search_memory(workspace_id: str, channel_id: str, query: str, include_all_status: bool = False) -> str:
    """
    Search the project memory database for decisions matching the query terms.
    Returns JSON string of matching decisions.
    """
    logger.info(f"Running search_memory for query: {query}")
    try:
        results = db.search_decisions(workspace_id, channel_id, query, include_all_status)
        return json.dumps(results)
    except Exception as e:
        logger.error(f"Error in search_memory tool: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def detect_conflict(workspace_id: str, channel_id: str, new_message: str, message_ts: str) -> str:
    """
    Compare a new message against confirmed decisions in the database.
    If a conflict is detected, logs it to the database as 'open' and returns the conflict details.
    Returns JSON string of conflict detection analysis (is_conflict, conflict_type, severity, explanation, conflict_id).
    """
    logger.info(f"Running detect_conflict on message: {new_message}")
    try:
        # 1. Fetch active confirmed decisions for channel
        active_decisions = db.get_all_active_decisions(workspace_id, channel_id)
        if not active_decisions:
            return json.dumps({"is_conflict": False, "explanation": "No confirmed memories to compare against."})

        # 2. Run LLM comparison
        result = llm.detect_conflict(new_message, active_decisions)

        # 3. If conflict is detected, save to conflicts table
        if result.get("is_conflict"):
            conflict_id = db.save_conflict(
                workspace_id=workspace_id,
                channel_id=channel_id,
                message_ts=message_ts,
                conflict_type=result.get("conflict_type", "unknown"),
                severity=result.get("severity", "medium"),
                new_message_summary=new_message[:100],
                conflicting_memory_id=result.get("conflicting_memory_id"),
                explanation=result.get("explanation", ""),
                status='open'
            )
            result["conflict_id"] = conflict_id
            
            # Fetch conflicting decision details to include in response
            conflict_decision = db.get_decision(result.get("conflicting_memory_id"))
            result["conflicting_decision"] = conflict_decision

        return json.dumps(result)
    except Exception as e:
        logger.error(f"Error in detect_conflict tool: {e}")
        return json.dumps({"error": str(e), "is_conflict": False})

@mcp.tool()
def verify_evidence(proposed_answer: str, evidence_messages_json: str, memory_items_json: str = "[]") -> str:
    """
    Verify if a proposed answer is supported by evidence messages.
    Returns JSON string containing verification details.
    """
    logger.info("Running verify_evidence tool")
    try:
        evidence_messages = json.loads(evidence_messages_json)
        memory_items = json.loads(memory_items_json)
        result = llm.verify_evidence(proposed_answer, evidence_messages, memory_items)
        return json.dumps(result)
    except Exception as e:
        logger.error(f"Error in verify_evidence tool: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def generate_project_summary(workspace_id: str, channel_id: str) -> str:
    """
    Generate a summary of confirmed decisions, open tasks, and conflicts in the channel.
    Returns JSON string containing formatted summary message.
    """
    logger.info(f"Running generate_project_summary for channel: {channel_id}")
    try:
        decisions = db.get_all_active_decisions(workspace_id, channel_id)
        tasks = db.get_channel_tasks(workspace_id, channel_id, status='open')
        conflicts = db.get_active_conflicts(workspace_id, channel_id)
        
        summary_text = llm.generate_project_summary(channel_id, decisions, tasks, conflicts)
        return json.dumps({"summary": summary_text})
    except Exception as e:
        logger.error(f"Error in generate_project_summary tool: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def reopen_decision(decision_id: int) -> str:
    """
    Change status of a decision to 'reopened' so it no longer triggers active conflicts.
    """
    logger.info(f"Running reopen_decision: {decision_id}")
    try:
        db.update_decision_status(decision_id, 'reopened')
        return json.dumps({"status": "success", "message": f"Decision #{decision_id} reopened."})
    except Exception as e:
        logger.error(f"Error in reopen_decision tool: {e}")
        return json.dumps({"status": "error", "error": str(e)})

@mcp.tool()
def log_conflict_action(conflict_id: int, action: str) -> str:
    """
    Update conflict status based on team actions (e.g. remind_decision -> 'resolved', ignore -> 'ignored', reopen_decision -> 'reopened_decision').
    If action is 'reopen_decision', also updates the conflicting decision status to 'reopened'.
    """
    logger.info(f"Running log_conflict_action: #{conflict_id} -> {action}")
    try:
        conflict = db.get_conflict(conflict_id)
        if not conflict:
            return json.dumps({"status": "error", "message": "Conflict not found"})

        if action == "ignore":
            db.update_conflict_status(conflict_id, "ignored")
        elif action == "remind_decision" or action == "resolve":
            db.update_conflict_status(conflict_id, "resolved")
        elif action == "reopen_decision":
            db.update_conflict_status(conflict_id, "reopened_decision")
            # Reopen the decision
            db.update_decision_status(conflict["conflicting_memory_id"], "reopened")

        return json.dumps({"status": "success", "message": f"Conflict action '{action}' recorded."})
    except Exception as e:
        logger.error(f"Error in log_conflict_action tool: {e}")
        return json.dumps({"status": "error", "error": str(e)})

if __name__ == "__main__":
    # Start the FastMCP server (runs stdio JSON-RPC transport loop)
    mcp.run()
