"""Run blocking work off the event loop, with a concurrency cap.

The repository (psycopg) and LLM (OpenAI SDK) calls are synchronous and would
otherwise block the asyncio event loop — so a single slow LLM call would stall
every other Slack event. `run_blocking` moves that work to a thread and bounds
how many run at once (so we don't exhaust the DB pool or hit LLM rate limits).

The semaphore is keyed by the running loop so tests (which create a fresh loop
per test) don't reuse a semaphore bound to a closed loop.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")

_semaphores: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max(1, get_settings().max_concurrency))
        _semaphores[loop] = sem
    return sem


async def run_blocking(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Execute a blocking callable in a worker thread, bounded by max_concurrency."""
    async with _semaphore():
        return await asyncio.to_thread(fn, *args, **kwargs)


def reset() -> None:
    """Test helper — drop cached per-loop semaphores."""
    _semaphores.clear()
