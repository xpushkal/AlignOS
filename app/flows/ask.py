"""Ask-question flow (PRD §17.1, §9.1).

Searches confirmed memory + live evidence, verifies support, and produces a
grounded answer — or a no-evidence refusal when support is insufficient (§9.6).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app import mcp_client
from app.config import get_settings
from app.store import get_store

# Single-flight registry: concurrent identical questions share one computation
# instead of each hitting the LLM (prevents a cache stampede under bursts).
_inflight: dict[str, asyncio.Future] = {}


async def answer_question(
    question: str,
    workspace_id: str,
    channel_id: str | None = None,
    evidence_messages: list[str] | None = None,
) -> dict[str, Any]:
    """Return a grounded answer dict for a memory question.

    Answers are cached per (workspace, channel, memory-version, question). The
    version is bumped whenever a decision is confirmed, so the cache is never
    stale. Skipped when live evidence is passed in (that path varies per call).
    Concurrent identical questions are coalesced via single-flight.
    """
    store = get_store()
    if evidence_messages:
        return await _compute(question, workspace_id, channel_id, evidence_messages, None)

    scope = f"{workspace_id}:{channel_id}"
    version = await store.get_version(scope)
    qnorm = " ".join(question.lower().split())
    cache_key = f"ans:{scope}:{version}:{qnorm}"

    hit = await store.cache_get(cache_key)
    if hit is not None:
        return json.loads(hit)

    # Coalesce concurrent identical requests onto a single in-flight computation.
    existing = _inflight.get(cache_key)
    if existing is not None:
        return await existing

    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _inflight[cache_key] = future
    try:
        result = await _compute(question, workspace_id, channel_id, None, cache_key)
        if not future.done():
            future.set_result(result)
        return result
    except Exception as exc:
        if not future.done():
            future.set_exception(exc)
        raise
    finally:
        _inflight.pop(cache_key, None)


async def _compute(
    question: str,
    workspace_id: str,
    channel_id: str | None,
    evidence_messages: list[str] | None,
    cache_key: str | None,
) -> dict[str, Any]:
    store = get_store()
    search = await mcp_client.call_tool(
        "search_memory",
        {"query": question, "workspace_id": workspace_id, "channel_id": channel_id},
    )
    memory_items = search.get("memory_items", [])

    # Generate a grounded answer from confirmed memory + live Slack evidence.
    gen = await mcp_client.call_tool(
        "generate_answer",
        {
            "question": question,
            "memory_items": memory_items,
            "evidence_messages": evidence_messages or [],
        },
    )

    support = gen.get("support_level", "INSUFFICIENT_EVIDENCE")
    refused = gen.get("refused", support == "INSUFFICIENT_EVIDENCE")
    confidence = gen.get("confidence", 0.0)

    if refused:
        source = "none"
    elif memory_items:
        source = "confirmed memory"
    elif evidence_messages:
        source = "live Slack evidence"
    else:
        source = "live discussion"

    result = {
        "answer": gen.get("answer", ""),
        "support_level": support,
        "confidence": confidence,
        "source": source,
        "refused": refused,
        "memory_items": memory_items,
    }

    if cache_key is not None:
        await store.cache_set(cache_key, json.dumps(result), get_settings().cache_ttl_seconds)
    return result
