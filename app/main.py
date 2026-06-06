"""AlignOS FastAPI backend entrypoint.

Exposes:
- Slack endpoints (/slack/events, /slack/interactions, /slack/commands) — wired
  to the Bolt app only when Slack is configured.
- Internal agent endpoints (/agent/ask, /agent/detect-decision,
  /agent/detect-conflict) for testing and orchestration without Slack.
- GET /health with backend/integration status.

Run: uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import concurrency, flows
from app.config import get_settings
from app.db import get_repository
from app.llm import get_llm_client
from app.store import get_store

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("alignos")

api = FastAPI(title="AlignOS", version="0.1.0")

# --- Slack wiring (only when configured) ---
_slack_handler = None
if settings.slack_configured:
    try:
        from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

        from app.slack.handlers import build_bolt_app

        _slack_handler = AsyncSlackRequestHandler(build_bolt_app())
        logger.info("Slack Bolt app wired.")
    except Exception as exc:  # pragma: no cover - optional dependency/runtime
        logger.warning("Slack not wired (%s).", exc)
else:
    logger.info("Slack not configured; /slack/* endpoints return 503.")


@api.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "db_backend": get_repository().backend,
        "llm_mode": get_llm_client().mode,
        "store_backend": get_store().backend,
        "slack_wired": _slack_handler is not None,
        "rts_enabled": settings.slack_rts_enabled,
        "inflight": concurrency.inflight(),
        "max_concurrency": settings.max_concurrency,
    }


# --- Slack endpoints ---
async def _slack(req: Request):
    if _slack_handler is None:
        return JSONResponse({"error": "Slack not configured"}, status_code=503)
    return await _slack_handler.handle(req)


@api.post("/slack/events")
async def slack_events(req: Request):
    return await _slack(req)


@api.post("/slack/interactions")
async def slack_interactions(req: Request):
    return await _slack(req)


@api.post("/slack/commands")
async def slack_commands(req: Request):
    return await _slack(req)


# --- Internal agent endpoints ---
async def agent_guard(
    request: Request, x_alignos_token: str | None = Header(default=None)
) -> None:
    """Protect /agent/* with optional shared-secret auth (V3) + rate limit (V1)."""
    token = get_settings().agent_api_token
    if token and x_alignos_token != token:
        raise HTTPException(status_code=401, detail="unauthorized")
    client_ip = request.client.host if request.client else "unknown"
    if not await get_store().rate_allow(f"agent:{client_ip}"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


class AskRequest(BaseModel):
    question: str
    workspace_id: str
    channel_id: str | None = None
    evidence_messages: list[str] | None = None


class DetectDecisionRequest(BaseModel):
    message: str
    workspace_id: str
    channel_id: str | None = None
    thread_context: str = ""
    recent_channel_context: str = ""


class DetectConflictRequest(BaseModel):
    message: str
    workspace_id: str
    channel_id: str | None = None
    message_ts: str | None = None
    recent_context: str = ""


@api.post("/agent/ask", dependencies=[Depends(agent_guard)])
async def agent_ask(body: AskRequest) -> dict:
    return await flows.answer_question(
        body.question, body.workspace_id, body.channel_id, body.evidence_messages
    )


@api.post("/agent/detect-decision", dependencies=[Depends(agent_guard)])
async def agent_detect_decision(body: DetectDecisionRequest) -> dict:
    return await flows.detect_and_propose(
        body.message,
        body.workspace_id,
        body.channel_id,
        body.thread_context,
        body.recent_channel_context,
    )


@api.post("/agent/detect-conflict", dependencies=[Depends(agent_guard)])
async def agent_detect_conflict(body: DetectConflictRequest) -> dict:
    return await flows.check_conflict(
        body.message,
        body.workspace_id,
        body.channel_id,
        message_ts=body.message_ts,
        recent_context=body.recent_context,
    )
