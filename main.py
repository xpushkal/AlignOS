import os
import json
import logging
import asyncio
from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AlignOS_App")

# Initialize Slack App
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")

app = AsyncApp(token=SLACK_BOT_TOKEN)

# Import local tools as backup fallback
import mcp_server as local_mcp

# Global MCP session reference
mcp_session = None

async def call_mcp_tool(name: str, arguments: dict) -> str:
    """
    Call an MCP tool. Uses the active stdio ClientSession if connected,
    otherwise falls back to local direct function invocation.
    """
    global mcp_session
    if mcp_session:
        try:
            logger.info(f"Calling MCP tool '{name}' over stdio client.")
            result = await mcp_session.call_tool(name, arguments)
            return result.content[0].text
        except Exception as e:
            logger.error(f"Error calling MCP tool {name} over stdio client: {e}. Using local fallback.")
    
    # Local fallback logic
    logger.info(f"Invoking local fallback for tool: {name}")
    try:
        if name == "detect_decision":
            return local_mcp.detect_decision(**arguments)
        elif name == "save_decision":
            return local_mcp.save_decision(**arguments)
        elif name == "search_memory":
            return local_mcp.search_memory(**arguments)
        elif name == "detect_conflict":
            return local_mcp.detect_conflict(**arguments)
        elif name == "verify_evidence":
            return local_mcp.verify_evidence(**arguments)
        elif name == "generate_project_summary":
            return local_mcp.generate_project_summary(**arguments)
        elif name == "reopen_decision":
            return local_mcp.reopen_decision(**arguments)
        elif name == "log_conflict_action":
            return local_mcp.log_conflict_action(**arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as ex:
        logger.error(f"Error executing local tool fallback: {ex}")
        return json.dumps({"status": "error", "error": str(ex)})

# Helper to fetch channel history for context
async def get_channel_context(client, channel_id: str, limit: int = 5, before_ts: str = None) -> str:
    """
    Retrieve message history context in standard text format.
    """
    try:
        res = await client.conversations_history(
            channel=channel_id,
            limit=limit,
            latest=before_ts
        )
        messages = res.get("messages", [])
        context_lines = []
        for msg in reversed(messages):
            user = msg.get("user", "User")
            text = msg.get("text", "")
            context_lines.append(f"{user}: {text}")
        return "\n".join(context_lines)
    except Exception as e:
        logger.error(f"Error retrieving context for channel {channel_id}: {e}")
        return ""

# Helper to fetch thread replies
async def get_thread_context(client, channel_id: str, thread_ts: str, limit: int = 10) -> str:
    try:
        res = await client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=limit
        )
        messages = res.get("messages", [])
        context_lines = []
        for msg in messages:
            user = msg.get("user", "User")
            text = msg.get("text", "")
            context_lines.append(f"{user}: {text}")
        return "\n".join(context_lines)
    except Exception as e:
        logger.error(f"Error retrieving replies for thread {thread_ts}: {e}")
        return ""

# App Mentions Listener
@app.event("app_mention")
async def handle_mentions(event, client, say):
    text = event.get("text", "")
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    workspace_id = event.get("team", "W001")
    user_id = event.get("user")

    # Clean the mention from the message text
    cleaned_text = text.replace(f"<@{event.get('parent_user_id', '')}>", "").strip()
    cleaned_text = cleaned_text.replace(f"<@{client.token}>", "").strip()
    
    # Regex/String mapping for help, summary, or questions
    lower_text = cleaned_text.lower()
    
    # 1. HELP Command
    if "help" in lower_text:
        help_msg = (
            "👋 *Hi there! I'm AlignOS*, your project alignment and decision intelligence agent.\n"
            "I observe conversations to keep a single, conflict-free memory layer.\n\n"
            "*Commands you can send me:*\n"
            "• `@AlignOS show project memory` - Shows a summary of confirmed decisions, tasks, and conflicts.\n"
            "• `@AlignOS reopen <decision_id>` - Reopen a decision by ID.\n"
            "• `@AlignOS what did we decide about <topic>?` - Ask questions about project decisions.\n\n"
            "*Automations:*\n"
            "• I will automatically detect potential decisions and post confirmation cards.\n"
            "• I will warn you of contradictions with confirmed memory."
        )
        await say(text=help_msg, thread_ts=thread_ts)
        return

    # 2. SHOW PROJECT MEMORY Command
    if "show project memory" in lower_text or "show memory" in lower_text:
        summary_raw = await call_mcp_tool(
            "generate_project_summary",
            {"workspace_id": workspace_id, "channel_id": channel_id}
        )
        summary_data = json.loads(summary_raw)
        summary_text = summary_data.get("summary", "Could not generate summary.")
        await say(text=summary_text, thread_ts=thread_ts)
        return

    # 3. REOPEN DECISION Command
    if "reopen" in lower_text:
        parts = cleaned_text.split()
        dec_id = None
        for p in parts:
            if p.isdigit():
                dec_id = int(p)
                break
        if dec_id is not None:
            reopen_raw = await call_mcp_tool("reopen_decision", {"decision_id": dec_id})
            reopen_data = json.loads(reopen_raw)
            if reopen_data.get("status") == "success":
                await say(text=f"Decision #{dec_id} has been reopened and removed from conflict checking.", thread_ts=thread_ts)
            else:
                await say(text=f"Error reopening decision #{dec_id}: {reopen_data.get('error')}", thread_ts=thread_ts)
        else:
            await say(text="Please specify the decision ID, e.g. `@AlignOS reopen 1`", thread_ts=thread_ts)
        return

    # 4. QUESTION ANSWERING FLOW
    # Fetch live search context fallback: get channel messages
    live_history = []
    try:
        res = await client.conversations_history(channel=channel_id, limit=20)
        for msg in res.get("messages", []):
            live_history.append({
                "slack_user_id": msg.get("user", "User"),
                "snippet": msg.get("text", ""),
                "slack_message_ts": msg.get("ts"),
                "slack_thread_ts": msg.get("thread_ts")
            })
    except Exception as e:
        logger.error(f"Failed to query channel history: {e}")

    # Search db memory
    search_raw = await call_mcp_tool("search_memory", {
        "workspace_id": workspace_id,
        "channel_id": channel_id,
        "query": cleaned_text
    })
    confirmed_memories = json.loads(search_raw)

    # Use LLM client logic via direct load
    from llm_client import LLMClient
    llm = LLMClient()
    answer = llm.generate_answer(cleaned_text, confirmed_memories, live_history)

    # Post answer
    await say(text=answer, thread_ts=thread_ts)

# Message monitoring for auto-detection of decisions and conflicts
@app.event("message")
async def handle_message_events(event, client, say):
    # Ignore bots and channel joins
    if event.get("bot_id") or event.get("subtype") or not event.get("text"):
        return

    text = event.get("text")
    channel_id = event.get("channel")
    message_ts = event.get("ts")
    thread_ts = event.get("thread_ts")
    workspace_id = event.get("team", "W001")

    # 1. CONFLICT DETECTION (check before creating new decisions)
    conflict_raw = await call_mcp_tool("detect_conflict", {
        "workspace_id": workspace_id,
        "channel_id": channel_id,
        "new_message": text,
        "message_ts": message_ts
    })
    conflict_res = json.loads(conflict_raw)

    if conflict_res.get("is_conflict"):
        conflict_id = conflict_res.get("conflict_id")
        explanation = conflict_res.get("explanation")
        
        # Post conflict card using Block Kit
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚠️ *Potential Conflict Detected!*\n{explanation}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Remind Decision"},
                        "style": "primary",
                        "value": f"conflict_remind:{conflict_id}",
                        "action_id": "conflict_remind_action"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reopen Decision"},
                        "style": "danger",
                        "value": f"conflict_reopen:{conflict_id}",
                        "action_id": "conflict_reopen_action"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Ignore"},
                        "value": f"conflict_ignore:{conflict_id}",
                        "action_id": "conflict_ignore_action"
                    }
                ]
            }
        ]
        await say(blocks=blocks, thread_ts=thread_ts or message_ts)
        return  # Stop if it's a conflict statement

    # 2. DECISION DETECTION
    # Get thread or channel context
    if thread_ts:
        context = await get_thread_context(client, channel_id, thread_ts)
    else:
        context = await get_channel_context(client, channel_id, limit=5, before_ts=message_ts)

    decision_raw = await call_mcp_tool("detect_decision", {
        "message": text,
        "thread_context": context
    })
    decision_res = json.loads(decision_raw)

    if decision_res.get("is_decision"):
        # Save proposed decision first to get ID
        evidence = [{"slack_message_ts": message_ts, "slack_thread_ts": thread_ts, "slack_user_id": event.get("user"), "snippet": text}]
        save_raw = await call_mcp_tool("save_decision", {
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "thread_ts": thread_ts or message_ts,
            "title": decision_res.get("title"),
            "summary": decision_res.get("summary"),
            "reason": decision_res.get("reason"),
            "status": "proposed",
            "confidence": decision_res.get("confidence", 0.0),
            "evidence_list_json": json.dumps(evidence)
        })
        save_res = json.loads(save_raw)
        
        if save_res.get("status") == "success":
            decision_id = save_res.get("decision_id")
            
            # Post confirmation Block Kit card
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"🤔 *Possible Decision Detected!*\n"
                            f"*Decision:* {decision_res.get('title')}\n"
                            f"*Summary:* {decision_res.get('summary')}\n"
                            f"*Reason:* {decision_res.get('reason') or 'None provided.'}\n"
                            f"*Confidence:* {int(decision_res.get('confidence', 0.0)*100)}%"
                        )
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Confirm"},
                            "style": "primary",
                            "value": f"decision_confirm:{decision_id}",
                            "action_id": "decision_confirm_action"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Reject"},
                            "style": "danger",
                            "value": f"decision_reject:{decision_id}",
                            "action_id": "decision_reject_action"
                        }
                    ]
                }
            ]
            await say(blocks=blocks, thread_ts=thread_ts or message_ts)

# Interactivity handling (Buttons)
@app.action("decision_confirm_action")
async def handle_confirm(ack, body, client, respond):
    await ack()
    value = body["actions"][0]["value"]
    decision_id = int(value.split(":")[1])
    user_id = body["user"]["id"]
    
    # Update status to confirmed
    import database as db
    db.update_decision_status(decision_id, "confirmed", confirmed_by_user_id=user_id)
    dec = db.get_decision(decision_id)
    
    await respond(f"✅ *Decision Confirmed* by <@{user_id}>: *{dec['title']}* saved to team memory.")

@app.action("decision_reject_action")
async def handle_reject(ack, body, client, respond):
    await ack()
    value = body["actions"][0]["value"]
    decision_id = int(value.split(":")[1])
    
    import database as db
    db.update_decision_status(decision_id, "rejected")
    
    await respond("❌ Decision proposal rejected.")

@app.action("conflict_remind_action")
async def handle_conflict_remind(ack, body, client, respond):
    await ack()
    value = body["actions"][0]["value"]
    conflict_id = int(value.split(":")[1])
    
    await call_mcp_tool("log_conflict_action", {"conflict_id": conflict_id, "action": "remind_decision"})
    await respond("Acknowledged. Reminded the team of the decision.")

@app.action("conflict_reopen_action")
async def handle_conflict_reopen(ack, body, client, respond):
    await ack()
    value = body["actions"][0]["value"]
    conflict_id = int(value.split(":")[1])
    
    await call_mcp_tool("log_conflict_action", {"conflict_id": conflict_id, "action": "reopen_decision"})
    await respond("⚠️ Conflicting decision has been reopened and marked for review.")

@app.action("conflict_ignore_action")
async def handle_conflict_ignore(ack, body, client, respond):
    await ack()
    value = body["actions"][0]["value"]
    conflict_id = int(value.split(":")[1])
    
    await call_mcp_tool("log_conflict_action", {"conflict_id": conflict_id, "action": "ignore"})
    await respond("Conflict warning ignored.")

# Setup standard main wrapper
async def main():
    # Attempt to start the MCP Server as subprocess
    global mcp_session
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
        env=os.environ.copy()
    )
    
    logger.info("Initializing Bolt App Socket Mode handler...")
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    
    try:
        logger.info("Starting stdio MCP client connection...")
        async with stdio_client(server_params) as (read_stream, write_stream):
            from mcp import ClientSession
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                mcp_session = session
                logger.info("MCP Stdio Session connected successfully.")
                
                # Start Bolt Socket Mode
                await handler.start_async()
    except Exception as e:
        logger.error(f"Failed to initialize stdio MCP connection: {e}. Starting Bolt in local-fallback mode.")
        # Launch without MCP subprocess connection, falling back to local imports
        await handler.start_async()

if __name__ == "__main__":
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        logger.error("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be configured. Check your .env file.")
    else:
        asyncio.run(main())
