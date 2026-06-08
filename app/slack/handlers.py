"""Slack Bolt wiring: app mentions, messages, and interactive buttons.

`build_bolt_app()` constructs an AsyncApp and registers handlers that delegate to
the agent flows. It is only called when Slack is configured (see app.main), so
importing this module never requires Slack credentials.
"""
from __future__ import annotations

import json
import logging
import re
import uuid

from app import flows
from app.concurrency import run_blocking
from app.intent import (
    CLEANUP_SUGGESTIONS,
    HELP,
    MEETING_TO_EXECUTION,
    QUESTION_ANSWERING,
    REOPEN_DECISION,
    SHOW_CONFLICTS,
    SHOW_HEALTH,
    SHOW_MEMORY,
    SHOW_TIMELINE,
    classify,
)
from app.security import sanitize_text
from app.slack import cards
from app.store import get_store

logger = logging.getLogger("alignos.slack")


async def _allowed(ws: str, user: str | None) -> bool:
    """Per-user rate-limit gate (V1), shared across instances via the store."""
    return await get_store().rate_allow(f"{ws}:{user or 'unknown'}")


async def _duplicate(event_id: str | None) -> bool:
    """Event idempotency (PRD §13.1, §14.2), shared across instances via the store."""
    return await get_store().seen(event_id)


def _team_id(body: dict, event: dict) -> str:
    """Workspace id. The envelope's `team_id` is canonical; `event["team"]` is a
    fallback and may be absent on some message payloads / org installs."""
    return body.get("team_id") or event.get("team") or ""


def build_bolt_app():
    from slack_bolt.async_app import AsyncApp

    from app.config import get_settings

    settings = get_settings()
    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    @app.event("app_mention")
    async def on_mention(event, say, body, client, context):
        logger.info("Received app_mention event: %s", event)
        if await _duplicate(body.get("event_id")):
            return
        ws = _team_id(body, event)
        ch = event.get("channel")
        user = event.get("user")
        if not await _allowed(ws, user):
            logger.warning("Rate limit hit for mention from %s in %s", user, ws)
            await say(text=":hourglass: You're sending requests too fast — try again shortly.")
            return
        text = sanitize_text(event.get("text", ""))
        intent = classify(text)

        if intent.name == HELP:
            await say(blocks=cards.help_blocks(), text="AlignOS help")
        elif intent.name == SHOW_MEMORY:
            summary = await flows.project_summary(ws, ch)
            await say(blocks=cards.summary_blocks(summary), text="Project memory")
        elif intent.name == SHOW_CONFLICTS:
            summary = await flows.project_summary(ws, ch)
            await say(blocks=cards.summary_blocks(summary), text="Conflicts")
        elif intent.name == SHOW_TIMELINE:
            timeline = await flows.get_timeline(ws, ch)
            await say(blocks=cards.timeline_blocks(timeline.get("timeline", [])), text="Decision Timeline")
        elif intent.name == SHOW_HEALTH:
            health = await flows.get_health_summary(ws, ch)
            await say(blocks=cards.project_health_card(health), text="Project Health Check")
        elif intent.name == CLEANUP_SUGGESTIONS:
            # Check Admin Permissions (Feature 4)
            allowed = True
            if settings.admin_user_ids:
                allowed = user in [uid.strip() for uid in settings.admin_user_ids.split(",")]
            if not allowed:
                await say(text=":warning: Memory cleanup is restricted to moderators/admins.")
                return
            suggestions = await flows.get_cleanup_suggestions(ws, ch)
            await say(blocks=cards.cleanup_suggestions_card(suggestions), text="Cleanup Suggestions")
        elif intent.name == MEETING_TO_EXECUTION:
            await say(text=":mag_right: Analyzing recent discussion to extract an execution plan...")
            # Query recent messages as discussion content
            evidence = await rts_history_helper(client, ch, context.bot_user_id, settings)
            if not evidence:
                await say(text=":warning: Insufficient channel history found to build an execution plan.")
                return
            discussion_text = "\n".join(evidence)
            plan = await flows.generate_plan(discussion_text)
            
            # Cache the plan using store to bypass Slack button char limit
            cache_key = f"exec:{uuid.uuid4()}"
            await get_store().cache_set(cache_key, json.dumps(plan), 600)
            await say(blocks=cards.execution_plan_card(plan, cache_key), text="Meeting Execution Plan")
        elif intent.name == QUESTION_ANSWERING:
            evidence = await rts_history_helper(client, ch, context.bot_user_id, settings)
            result = await flows.answer_question(
                intent.topic or text, ws, ch, evidence_messages=evidence
            )
            await say(blocks=cards.answer_blocks(result), text=result.get("answer", ""))
        elif intent.name == REOPEN_DECISION:
            await say(text=f"Looking for a decision about '{intent.topic}' to reopen…")
        else:
            # Bug fix: When tagged with a decision, reminder, or conflict, handle it instead of showing help guide.
            # We strip ONLY the bot's mention to preserve other user mentions in the message.
            bot_id = context.bot_user_id
            if bot_id:
                clean_text = re.sub(rf"<@{bot_id}(\|[^>]+)?>", "", text).strip()
            else:
                clean_text = re.sub(r"^<@[A-Z0-9]+>", "", text).strip()
            
            # 1. Check for personal deadline reminder cues
            reminder_det = await flows.detect_reminder(clean_text)
            if reminder_det.get("has_reminder"):
                owner_id = reminder_det.get("owner_slack_id")
                if not owner_id or str(owner_id).lower() in ("me", "none", "my", ""):
                    owner_id = f"<@{user}>"
                payload = {
                    "task_title": reminder_det.get("task_title"),
                    "owner_slack_id": owner_id,
                    "deadline": reminder_det.get("deadline"),
                    "remind_at": reminder_det.get("remind_at"),
                }
                val = json.dumps(payload)
                blocks = [
                    cards._section("⏰ *Task Deadline Reminder Detected*"),
                    cards._section(f"*Task:* {reminder_det.get('task_title')}\n*Owner:* {owner_id}\n*Deadline:* {reminder_det.get('deadline')}"),
                    {
                        "type": "actions",
                        "block_id": "reminder_actions",
                        "elements": [
                            cards._button("Confirm Reminder", "reminder_confirm", val, style="primary"),
                            cards._button("Dismiss", "reminder_dismiss", val),
                        ]
                    }
                ]
                await say(blocks=blocks, text="Deadline reminder detected")
                return

            # 2. Check for conflicts
            ts = event.get("ts")
            conflict = await flows.check_conflict(clean_text, ws, ch, message_ts=ts)
            if conflict["conflict"]:
                detection = conflict["detection"]
                conflict_id = conflict["conflict_id"]
                memory_id = detection.get("conflicting_memory_id")
                if memory_id:
                    from app.db import get_repository
                    old_dec = await run_blocking(get_repository().get_decision, memory_id)
                    if old_dec:
                        new_dec = {
                            "title": clean_text[:60],
                            "summary": clean_text,
                            "reason": "Indicated by new message",
                        }
                        await say(
                            blocks=cards.decision_comparison_card(old_dec, new_dec, detection.get("explanation", ""), conflict_id),
                            text="New vs Old Decision Comparison",
                        )
                        return
                await say(
                    blocks=cards.conflict_card(detection, conflict_id),
                    text="Possible conflict detected",
                )
                return

            # 3. Check for decisions
            proposal = await flows.detect_and_propose(clean_text, ws, ch)
            if proposal["proposed"]:
                decision = dict(proposal["decision"])
                decision["original_message"] = clean_text
                
                related_id = None
                from app.db import get_repository
                matches = await run_blocking(get_repository().search_memory, decision.get("title", ""), ws, ch)
                dec_matches = [m for m in matches if m.get("type") == "decision" and m.get("status") == "confirmed"]
                if dec_matches:
                    related_id = dec_matches[0]["id"]
                    
                await say(blocks=cards.decision_card(decision, related_id), text="Possible decision detected")
                return

            # Default fallback to help blocks
            await say(blocks=cards.help_blocks(), text="AlignOS")

    @app.event("message")
    async def on_message(event, say, body, context):
        logger.info("Received message event: %s", event)
        if await _duplicate(body.get("event_id")):
            return
        # Ignore bot messages / edits to prevent loops (PRD §13.1).
        if event.get("bot_id") or event.get("subtype"):
            return
        raw_text = event.get("text", "")
        # Mentions are commands handled by on_mention; don't also process them as
        # passive messages (avoids double replies). Decisions/conflicts are
        # detected from plain channel messages.
        if context.bot_user_id and f"<@{context.bot_user_id}>" in raw_text:
            return

        ws = _team_id(body, event)
        ch = event.get("channel")
        user = event.get("user")
        ts = event.get("ts")
        if not await _allowed(ws, user):
            logger.warning("Rate limit hit for message from %s in %s", user, ws)
            return
        text = sanitize_text(raw_text)

        # 1. Check for personal deadline reminder cues (Feature 9)
        reminder_det = await flows.detect_reminder(text)
        if reminder_det.get("has_reminder"):
            owner_id = reminder_det.get("owner_slack_id")
            if not owner_id or str(owner_id).lower() in ("me", "none", "my", ""):
                owner_id = f"<@{user}>"
            payload = {
                "task_title": reminder_det.get("task_title"),
                "owner_slack_id": owner_id,
                "deadline": reminder_det.get("deadline"),
                "remind_at": reminder_det.get("remind_at"),
            }
            val = json.dumps(payload)
            blocks = [
                cards._section(f"⏰ *Task Deadline Reminder Detected*"),
                cards._section(f"*Task:* {reminder_det.get('task_title')}\n*Owner:* {owner_id}\n*Deadline:* {reminder_det.get('deadline')}"),
                {
                    "type": "actions",
                    "block_id": "reminder_actions",
                    "elements": [
                        cards._button("Confirm Reminder", "reminder_confirm", val, style="primary"),
                        cards._button("Dismiss", "reminder_dismiss", val),
                    ]
                }
            ]
            await say(blocks=blocks, text="Deadline reminder detected")
            return

        # 2. Conflict detection
        conflict = await flows.check_conflict(text, ws, ch, message_ts=ts)
        if conflict["conflict"]:
            detection = conflict["detection"]
            conflict_id = conflict["conflict_id"]
            memory_id = detection.get("conflicting_memory_id")
            if memory_id:
                from app.db import get_repository
                old_dec = await run_blocking(get_repository().get_decision, memory_id)
                if old_dec:
                    new_dec = {
                        "title": text[:60],
                        "summary": text,
                        "reason": "Indicated by new message",
                    }
                    await say(
                        blocks=cards.decision_comparison_card(old_dec, new_dec, detection.get("explanation", ""), conflict_id),
                        text="New vs Old Decision Comparison",
                    )
                    return
            await say(
                blocks=cards.conflict_card(detection, conflict_id),
                text="Possible conflict detected",
            )
            return

        # 3. Decision detection
        proposal = await flows.detect_and_propose(text, ws, ch)
        if proposal["proposed"]:
            decision = dict(proposal["decision"])
            decision["original_message"] = text
            
            # Check for existing overlapping confirmed decisions (Feature 3)
            related_id = None
            from app.db import get_repository
            matches = await run_blocking(get_repository().search_memory, decision.get("title", ""), ws, ch)
            dec_matches = [m for m in matches if m.get("type") == "decision" and m.get("status") == "confirmed"]
            if dec_matches:
                related_id = dec_matches[0]["id"]
                
            await say(blocks=cards.decision_card(decision, related_id), text="Possible decision detected")

    # --- interactive buttons ---
    @app.action("decision_confirm")
    async def confirm(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        ch = body.get("channel", {}).get("id")
        user = body.get("user", {}).get("id")
        decision = _decision_from_value(_action_value(body))
        result = await flows.confirm_decision(decision, ws, ch, confirmed_by=user)
        
        # Save decision ID to prompt for PRD impact (Feature 8)
        dec_id = result.get("decision_id")
        await say(text=f":white_check_mark: Decision saved ({result.get('status')}).")
        
        # Determine if it affects product scope and suggest PRD update
        if dec_id and decision.get("prd_impact", True):
            blocks = [
                cards._section(":warning: *PRD Impact Alert:* This confirmed decision might change the product scope. Do you want to update the PRD?"),
                {
                    "type": "actions",
                    "block_id": "prd_trigger_actions",
                    "elements": [
                        cards._button("Suggest PRD Update", "suggest_prd_update", dec_id, style="primary"),
                        cards._button("Ignore", "evidence_ignore", "ignore"),
                    ]
                }
            ]
            await say(blocks=blocks, text="PRD impact check")

    @app.action("decision_reject")
    async def reject(ack, say):
        await ack()
        await say(text="Decision rejected. Nothing was saved.")

    @app.action("decision_reopen_related")
    async def reopen_related(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        val = _action_value(body)
        from app import mcp_client
        # If val is a UUID, reopen it. If it is a string, search and reopen.
        decision_id = val
        if len(val) != 36: # Not a UUID
            from app.db import get_repository
            matches = await run_blocking(get_repository().search_memory, val, ws)
            dec_matches = [m for m in matches if m.get("type") == "decision"]
            if dec_matches:
                decision_id = dec_matches[0]["id"]
            else:
                await say(text=f":warning: Could not find matching related decision for '{val}'.")
                return
        
        await mcp_client.call_tool("reopen_decision", {"decision_id": decision_id, "workspace_id": ws})
        await say(text=f":recycle: Reopened related decision for discussion.")

    @app.action("conflict_ignore")
    async def ignore_conflict(ack, body, say):
        await ack()
        from app import mcp_client
        await mcp_client.call_tool(
            "log_conflict_action",
            {"conflict_id": _action_value(body), "action": "ignore"},
        )
        await say(text="Conflict ignored. I won't alert again for this one.")

    @app.action("conflict_reopen")
    async def reopen_conflict(ack, body, say):
        await ack()
        from app import mcp_client
        await mcp_client.call_tool(
            "log_conflict_action",
            {"conflict_id": _action_value(body), "action": "reopen"},
        )
        await say(text="Decision reopened for discussion.")

    # Decision Comparison Handlers (Feature 6)
    @app.action("decision_supersede")
    async def supersede(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        ch = body.get("channel", {}).get("id")
        user = body.get("user", {}).get("id")
        val = json.loads(_action_value(body))
        
        # 1. Mark old decision as superseded
        from app import mcp_client
        await mcp_client.call_tool("execute_cleanup_action", {
            "action": "supersede",
            "item_id": val["old_id"],
            "target_id": val["old_id"], # We can reference it
        })
        
        # 2. Confirm new decision
        result = await flows.confirm_decision(val["new_decision"], ws, ch, confirmed_by=user)
        
        # 3. Resolve conflict status
        await mcp_client.call_tool("log_conflict_action", {
            "conflict_id": val["conflict_id"],
            "action": "resolve"
        })
        await say(text=f":white_check_mark: Old decision superseded. New decision saved.")

    @app.action("decision_keep_both")
    async def keep_both(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        ch = body.get("channel", {}).get("id")
        user = body.get("user", {}).get("id")
        val = json.loads(_action_value(body))
        
        # Save new decision and resolve conflict
        await flows.confirm_decision(val["new_decision"], ws, ch, confirmed_by=user)
        from app import mcp_client
        await mcp_client.call_tool("log_conflict_action", {
            "conflict_id": val["conflict_id"],
            "action": "resolve"
        })
        await say(text=f":white_check_mark: Kept both decisions. Conflict resolved.")

    @app.action("decision_mark_conflict")
    async def mark_conflict(ack, body, say):
        await ack()
        await say(text="Decision marked as unresolved conflict.")

    # Cleanup actions (Feature 4)
    @app.action("cleanup_archive")
    async def cleanup_archive(ack, body, say):
        await ack()
        val = _action_value(body)
        await flows.execute_action("archive", val)
        await say(text=f":checkered_flag: Memory item {val[:8]} archived.")

    @app.action("cleanup_delete")
    async def cleanup_delete(ack, body, say):
        await ack()
        val = _action_value(body)
        await flows.execute_action("delete", val)
        await say(text=f":wastebasket: Memory item {val[:8]} deleted.")

    @app.action("cleanup_ignore")
    async def cleanup_ignore(ack, body, say):
        await ack()
        val = _action_value(body)
        await flows.execute_action("ignore", val)
        await say(text="Cleanup suggestion ignored.")

    @app.action("cleanup_merge")
    async def cleanup_merge(ack, body, say):
        await ack()
        val = _action_value(body)
        prim, dupe = val.split(":")
        await flows.execute_action("merge", prim, dupe)
        await say(text=f":chains: Duplicate task {dupe[:8]} merged into primary task {prim[:8]}.")

    # Execution Plan persistence (Feature 5)
    @app.action("execution_persist")
    async def execution_persist(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        ch = body.get("channel", {}).get("id")
        val = _action_value(body)
        
        plan_str = await get_store().cache_get(val)
        if not plan_str:
            await say(text=":warning: Execution plan session expired. Propose plan again.")
            return
            
        plan = json.loads(plan_str)
        result = await flows.persist_plan(plan, ws, ch)
        await say(
            text=f":rocket: Plan persisted! Saved {len(result['decisions'])} decisions, "
                 f"{len(result['tasks'])} tasks, and {len(result['blockers'])} blockers."
        )

    # PRD Updater actions (Feature 8)
    @app.action("suggest_prd_update")
    async def suggest_prd(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        dec_id = _action_value(body)
        
        suggestions_res = await flows.get_prd_suggestions(dec_id, ws)
        suggestions = suggestions_res.get("suggestions", [])
        if not suggestions:
            await say(text="No PRD updates recommended for this decision.")
            return
            
        cache_key = f"prd:{uuid.uuid4()}"
        await get_store().cache_set(cache_key, json.dumps(suggestions), 600)
        await say(blocks=cards.prd_suggestions_blocks(suggestions, cache_key), text="PRD Suggestions")

    @app.action("prd_apply")
    async def prd_apply(ack, body, say):
        await ack()
        val = _action_value(body)
        sug_str = await get_store().cache_get(val)
        if not sug_str:
            await say(text=":warning: PRD suggestions session expired.")
            return
        suggestions = json.loads(sug_str)
        success = await flows.apply_prd_suggestions(suggestions)
        if success:
            await say(text=":notebook_with_decorative_cover: Requirements successfully written to `Docs/prd.md`.")
        else:
            await say(text=":warning: Failed to find `Docs/prd.md` file.")

    # Reminder confirmations (Feature 9)
    @app.action("reminder_confirm")
    async def reminder_confirm(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        val = json.loads(_action_value(body))
        await flows.schedule_reminder(
            workspace_id=ws,
            task_title=val["task_title"],
            owner_slack_id=val["owner_slack_id"],
            deadline=val["deadline"],
            remind_at=val["remind_at"],
        )
        await say(text=f":white_check_mark: Personal deadline reminder scheduled for {val['owner_slack_id']}.")

    @app.action("reminder_dismiss")
    async def reminder_dismiss(ack, say):
        await ack()
        await say(text="Reminder dismissed.")

    # Acknowledge remaining buttons
    for action_id in (
        "decision_edit",
        "conflict_remind",
        "evidence_start_thread",
        "evidence_search_again",
        "evidence_ignore",
    ):
        app.action(action_id)(_ack_only)

    return app


async def rts_history_helper(client, ch, bot_user_id, settings) -> list[str] | None:
    if settings.slack_rts_enabled:
        from app import rts
        return await rts.fetch_channel_evidence(
            client, ch, limit=settings.rts_history_limit,
            exclude_user=bot_user_id,
        ) or None
    return None


async def _ack_only(ack):
    await ack()


def _action_value(body: dict) -> str:
    actions = body.get("actions", [])
    return actions[0].get("value", "") if actions else ""


def _decision_from_value(raw: str) -> dict:
    """Decode the decision payload carried in the Confirm button value.

    The card encodes the full detected decision as JSON so confirmation preserves
    the summary/reason/original message (not just the title). Falls back to
    treating the value as a plain title for older cards.
    """
    try:
        decision = json.loads(raw)
        if not isinstance(decision, dict):
            raise ValueError
    except Exception:
        return {"title": raw, "summary": raw}

    # Fold the original message into the summary so it's searchable later.
    original = decision.get("original_message")
    summary = decision.get("summary") or ""
    if original and original.lower() not in summary.lower():
        decision["summary"] = f"{summary} — {original}".strip(" —")
    return decision
