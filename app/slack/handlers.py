"""Slack Bolt wiring: app mentions, messages, and interactive buttons.

`build_bolt_app()` constructs an AsyncApp and registers handlers that delegate to
the agent flows. It is only called when Slack is configured (see app.main), so
importing this module never requires Slack credentials.
"""
from __future__ import annotations

import logging

from app import flows
from app.intent import (
    HELP,
    POSSIBLE_CONFLICT,
    QUESTION_ANSWERING,
    REOPEN_DECISION,
    SHOW_CONFLICTS,
    SHOW_MEMORY,
    classify,
)
from app.security import get_user_limiter, sanitize_text
from app.slack import cards

logger = logging.getLogger("alignos.slack")


def _allowed(ws: str, user: str | None) -> bool:
    """Per-user rate-limit gate (V1). Missing user id falls back to workspace."""
    return get_user_limiter().check(f"{ws}:{user or 'unknown'}")


def build_bolt_app():
    from slack_bolt.async_app import AsyncApp

    from app.config import get_settings

    settings = get_settings()
    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    @app.event("app_mention")
    async def on_mention(event, say):
        ws = event.get("team", "")
        ch = event.get("channel")
        user = event.get("user")
        if not _allowed(ws, user):
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
        elif intent.name == QUESTION_ANSWERING:
            result = await flows.answer_question(intent.topic or text, ws, ch)
            await say(blocks=cards.answer_blocks(result), text=result.get("answer", ""))
        elif intent.name == REOPEN_DECISION:
            await say(text=f"Looking for a decision about '{intent.topic}' to reopen…")
        else:
            await say(blocks=cards.help_blocks(), text="AlignOS")

    @app.event("message")
    async def on_message(event, say):
        # Ignore bot messages / edits to prevent loops (PRD §13.1).
        if event.get("bot_id") or event.get("subtype"):
            return
        ws = event.get("team", "")
        ch = event.get("channel")
        user = event.get("user")
        ts = event.get("ts")
        # Passive scanning: silently drop when over the limit (no reply, to avoid
        # amplification), but still bound the LLM/DB work it would trigger.
        if not _allowed(ws, user):
            logger.warning("Rate limit hit for message from %s in %s", user, ws)
            return
        text = sanitize_text(event.get("text", ""))

        # Decision detection
        proposal = await flows.detect_and_propose(text, ws, ch)
        if proposal["proposed"]:
            await say(blocks=cards.decision_card(proposal["decision"]), text="Possible decision detected")
            return

        # Conflict detection
        conflict = await flows.check_conflict(text, ws, ch, message_ts=ts)
        if conflict["conflict"]:
            await say(
                blocks=cards.conflict_card(conflict["detection"], conflict["conflict_id"]),
                text="Possible conflict detected",
            )

    # --- interactive buttons ---
    @app.action("decision_confirm")
    async def confirm(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        ch = body.get("channel", {}).get("id")
        user = body.get("user", {}).get("id")
        decision = {"title": _action_value(body), "summary": _action_value(body)}
        result = await flows.confirm_decision(decision, ws, ch, confirmed_by=user)
        await say(text=f":white_check_mark: Decision saved ({result.get('status')}).")

    @app.action("decision_reject")
    async def reject(ack, say):
        await ack()
        await say(text="Decision rejected. Nothing was saved.")

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

    # Acknowledge remaining buttons so Slack doesn't show an error.
    for action_id in (
        "decision_edit",
        "conflict_remind",
        "evidence_start_thread",
        "evidence_search_again",
        "evidence_ignore",
    ):
        app.action(action_id)(_ack_only)

    return app


async def _ack_only(ack):
    await ack()


def _action_value(body: dict) -> str:
    actions = body.get("actions", [])
    return actions[0].get("value", "") if actions else ""
