"""Tests for off-loading blocking work and bounding concurrency."""
import asyncio
import time

from app import concurrency


async def test_run_blocking_returns_value():
    assert await concurrency.run_blocking(lambda x: x * 2, 21) == 42


async def test_blocking_work_runs_in_parallel():
    """5 blocking sleeps should overlap (not serialize) when offloaded."""
    concurrency.reset()
    start = time.perf_counter()
    await asyncio.gather(*[concurrency.run_blocking(time.sleep, 0.2) for _ in range(5)])
    elapsed = time.perf_counter() - start
    # Serial would be ~1.0s; parallel (cap 8) should be well under.
    assert elapsed < 0.6


async def test_concurrency_cap_is_enforced(monkeypatch):
    """With cap=2, four 0.2s tasks run in two waves (~0.4s)."""
    from app.config import get_settings

    monkeypatch.setenv("MAX_CONCURRENCY", "2")
    get_settings.cache_clear()
    concurrency.reset()

    start = time.perf_counter()
    await asyncio.gather(*[concurrency.run_blocking(time.sleep, 0.2) for _ in range(4)])
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.35  # cannot be faster than 2 waves
    assert elapsed < 0.8

    get_settings.cache_clear()
    concurrency.reset()
