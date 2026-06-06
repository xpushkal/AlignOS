"""Run AlignOS via Slack Socket Mode — no public URL / ngrok needed.

Ideal for local testing. Requires SLACK_BOT_TOKEN and SLACK_APP_TOKEN
(xapp-…, with the connections:write scope), plus Socket Mode and event
subscriptions (app_mention, message.channels) enabled in the Slack app config.

Run: python -m app.socket_mode
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.db import get_repository
from app.llm import get_llm_client
from app.slack.handlers import build_bolt_app

logger = logging.getLogger("alignos.socket")


async def _run() -> None:
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    settings = get_settings()
    if not settings.slack_bot_token or not settings.slack_app_token:
        raise SystemExit(
            "Socket Mode requires SLACK_BOT_TOKEN and SLACK_APP_TOKEN in your .env."
        )

    app = build_bolt_app()
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    logger.info(
        "Starting AlignOS in Socket Mode (db=%s, llm=%s)…",
        get_repository().backend,
        get_llm_client().mode,
    )
    await handler.start_async()


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
