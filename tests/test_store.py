"""Tests for the shared state store (in-memory backend) and answer caching."""
import asyncio

import pytest

from app import flows
from app.store import InMemoryStore, get_store, reset_store


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_store()
    yield
    reset_store()


async def test_rate_allow_respects_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("RATE_LIMIT_MAX_CALLS", "3")
    get_settings.cache_clear()
    store = InMemoryStore()
    assert [await store.rate_allow("k") for _ in range(3)] == [True, True, True]
    assert await store.rate_allow("k") is False
    assert await store.rate_allow("other") is True  # independent key
    get_settings.cache_clear()


async def test_seen_dedupes():
    store = InMemoryStore()
    assert await store.seen("e1") is False
    assert await store.seen("e1") is True
    assert await store.seen(None) is False


async def test_cache_get_set_and_version_invalidation():
    store = InMemoryStore()
    await store.cache_set("k", "v", ttl=60)
    assert await store.cache_get("k") == "v"
    assert await store.get_version("scope") == 0
    assert await store.bump_version("scope") == 1
    assert await store.get_version("scope") == 2 - 1


async def test_answer_cache_hit_skips_llm(monkeypatch):
    """A repeated identical question is served from cache (no second LLM call)."""
    WS, CH = "T", "C"
    # seed a confirmed decision so the answer is cacheable (not a refusal)
    prop = await flows.detect_and_propose("Okay final, we'll use Postgres for v1.", WS, CH)
    d = dict(prop["decision"]); d["original_message"] = "Okay final, we'll use Postgres for v1."
    await flows.confirm_decision(d, WS, CH, confirmed_by="U1")

    calls = []
    from app.flows import ask as ask_flow

    real = ask_flow.mcp_client.call_tool

    async def spy(name, args):
        calls.append(name)
        return await real(name, args)

    monkeypatch.setattr(ask_flow.mcp_client, "call_tool", spy)

    q = "what did we decide about postgres?"
    first = await flows.answer_question(q, WS, CH)
    n_after_first = len(calls)
    second = await flows.answer_question(q, WS, CH)

    assert first == second
    assert len(calls) == n_after_first  # cache hit: no further tool/LLM calls


async def test_concurrent_identical_questions_coalesce(monkeypatch):
    """A burst of identical questions should hit the LLM once (single-flight)."""
    WS, CH = "T", "C3"
    prop = await flows.detect_and_propose("Okay final, we'll use Postgres for v1.", WS, CH)
    d = dict(prop["decision"]); d["original_message"] = "Okay final, we'll use Postgres for v1."
    await flows.confirm_decision(d, WS, CH, confirmed_by="U1")

    calls = []
    from app.flows import ask as ask_flow

    real = ask_flow.mcp_client.call_tool

    async def spy(name, args):
        calls.append(name)
        await asyncio.sleep(0.05)  # widen the race window
        return await real(name, args)

    monkeypatch.setattr(ask_flow.mcp_client, "call_tool", spy)

    q = "what did we decide about postgres?"
    results = await asyncio.gather(*[flows.answer_question(q, WS, CH) for _ in range(10)])

    assert all(r == results[0] for r in results)
    # Without coalescing this would be ~20 calls (search+verify x10); with it, ~2.
    assert len(calls) <= 2


async def test_confirm_decision_invalidates_answer_cache():
    WS, CH = "T", "C2"
    q = "what did we decide about the database?"
    # ask before any decision -> refusal, cached
    before = await flows.answer_question(q, WS, CH)
    assert before["refused"] is True

    prop = await flows.detect_and_propose("Okay final, we'll use Postgres for v1.", WS, CH)
    d = dict(prop["decision"]); d["original_message"] = "Okay final, we'll use Postgres for v1."
    await flows.confirm_decision(d, WS, CH, confirmed_by="U1")  # bumps version

    after = await flows.answer_question(q, WS, CH)
    assert after["refused"] is False  # not served stale from cache
