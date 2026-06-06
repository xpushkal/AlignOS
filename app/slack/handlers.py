"""Slack Bolt wiring: app mentions, messages, and interactive buttons.

`build_bolt_app()` constructs an AsyncApp and registers handlers that delegate to
the agent flows. It is only called when Slack is configured (see app.main), so
importing this module never requires Slack credentials.
"""
from __future__ import annotations

import json
import logging
from collections import deque

from app import flows
from app.intent import (
    HELP,
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


# --- event idempotency (PRD §13.1, §14.2): dedupe by Slack event_id so retries
# and redeliveries are processed at most once. Bounded in-memory set.
_SEEN_MAX = 4000
_seen_ids: deque[str] = deque(maxlen=_SEEN_MAX)
_seen_set: set[str] = set()


def _duplicate(event_id: str | None) -> bool:
    if not event_id:
        return False
    if event_id in _seen_set:
        return True
    _seen_ids.append(event_id)
    _seen_set.add(event_id)
    if len(_seen_set) > _SEEN_MAX:
        _seen_set.intersection_update(_seen_ids)
    return False


def build_bolt_app():
    from slack_bolt.async_app import AsyncApp

    from app.config import get_settings

    settings = get_settings()
    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )

    @app.event("app_mention")
    async def on_mention(event, say, body):
        if _duplicate(body.get("event_id")):
            return
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
    async def on_message(event, say, body, context):
        if _duplicate(body.get("event_id")):
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

        ws = event.get("team", "")
        ch = event.get("channel")
        user = event.get("user")
        ts = event.get("ts")
        if not _allowed(ws, user):
            logger.warning("Rate limit hit for message from %s in %s", user, ws)
            return
        text = sanitize_text(raw_text)

        # Conflict detection FIRST: a message that contradicts confirmed memory
        # (e.g. "I'll start MongoDB setup." vs a confirmed PostgreSQL decision) is
        # a conflict, not a new decision (PRD §17.3).
        conflict = await flows.check_conflict(text, ws, ch, message_ts=ts)
        if conflict["conflict"]:
            await say(
                blocks=cards.conflict_card(conflict["detection"], conflict["conflict_id"]),
                text="Possible conflict detected",
            )
            return

        # Otherwise, see if it's a new decision.
        proposal = await flows.detect_and_propose(text, ws, ch)
        if proposal["proposed"]:
            decision = dict(proposal["decision"])
            decision["original_message"] = text
            await say(blocks=cards.decision_card(decision), text="Possible decision detected")

    # --- interactive buttons ---
    @app.action("decision_confirm")
    async def confirm(ack, body, say):
        await ack()
        ws = body.get("team", {}).get("id", "")
        ch = body.get("channel", {}).get("id")
        user = body.get("user", {}).get("id")
        decision = _decision_from_value(_action_value(body))
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
