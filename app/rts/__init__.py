"""Real-time Slack context retrieval (the "live evidence" layer, PRD §7.1).

Slack's message-search API requires a user token + paid plan, so for the MVP we
use `conversations.history` (available with the bot's `channels:history` /
`groups:history` scopes) to pull recent channel messages as live evidence. These
are passed to the answer flow alongside confirmed memory.

Gated by `SLACK_RTS_ENABLED`; falls back to an empty list on any error so Q&A
degrades gracefully to confirmed-memory-only.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("alignos.rts")


async def fetch_channel_evidence(
    client,
    channel_id: str | None,
    limit: int = 20,
    exclude_user: str | None = None,
) -> list[str]:
    """Return recent human message texts from a channel (newest first)."""
    if not channel_id:
        return []
    try:
        resp = await client.conversations_history(channel=channel_id, limit=limit)
    except Exception as exc:  # missing scope, not in channel, rate limit, etc.
        logger.warning("RTS conversations.history failed for %s: %s", channel_id, exc)
        return []

    evidence: list[str] = []
    for msg in resp.get("messages", []):
        if msg.get("bot_id") or msg.get("subtype"):
            continue  # skip bot/system messages
        if exclude_user and msg.get("user") == exclude_user:
            continue
        text = (msg.get("text") or "").strip()
        if text:
            evidence.append(text)
    return evidence
