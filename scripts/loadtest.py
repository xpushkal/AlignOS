"""Concurrency load test for the AlignOS pipeline (real Neon + OpenRouter).

Usage:
    python scripts/loadtest.py [N]      # N = concurrent Q&A requests (default 25)

Seeds one confirmed decision in a throwaway channel, then fires N concurrent
answer_question calls and reports latency percentiles, throughput, and how many
requests actually reached the LLM (gating + answer cache should keep this low).
Cleans up the throwaway channel afterwards.

This measures the core pipeline (DB + LLM), which is the real load driver — not
the Slack transport.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# Allow running as `python scripts/loadtest.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import dotenv_values


def _load_env() -> None:
    for k, v in dotenv_values(".env").items():
        if v is not None:
            os.environ[k] = v


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
    return s[idx]


async def main(n: int) -> None:
    _load_env()
    # Count real LLM calls by wrapping the LLM client.
    import app.llm.client as llm_client

    llm_calls = {"n": 0}
    original = llm_client.LLMClient._json_or_heuristic

    def counting(self, prompt, fallback):
        if self._client:
            llm_calls["n"] += 1
        return original(self, prompt, fallback)

    llm_client.LLMClient._json_or_heuristic = counting

    from app import flows
    from app.db import get_repository

    ws, ch = "T_LOADTEST", f"C_LOADTEST_{int(time.time())}"
    print(f"backend: db={get_repository().backend}  workers/cap=MAX_CONCURRENCY")

    # Seed one confirmed decision.
    prop = await flows.detect_and_propose("Okay final, we'll use PostgreSQL for v1.", ws, ch)
    d = dict(prop["decision"]); d["original_message"] = "Okay final, we'll use PostgreSQL for v1."
    await flows.confirm_decision(d, ws, ch, confirmed_by="U_LOAD")

    question = "what did we decide about postgresql?"
    llm_calls["n"] = 0

    async def one() -> float:
        s = time.perf_counter()
        await flows.answer_question(question, ws, ch)
        return time.perf_counter() - s

    wall_start = time.perf_counter()
    latencies = await asyncio.gather(*[one() for _ in range(n)])
    wall = time.perf_counter() - wall_start

    print(f"\n{n} concurrent Q&A requests")
    print(f"  wall time:     {wall:.2f}s")
    print(f"  throughput:    {n / wall:.1f} req/s")
    print(f"  latency p50:   {_pct(latencies, 50):.2f}s")
    print(f"  latency p95:   {_pct(latencies, 95):.2f}s")
    print(f"  latency max:   {max(latencies):.2f}s")
    print(f"  LLM calls:     {llm_calls['n']}  (of {n} requests — rest served from cache)")

    # Cleanup
    try:
        import psycopg

        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c, c.cursor() as cur:
            for t in ("conflicts", "memory_items", "decisions"):
                cur.execute(f"delete from {t} where channel_id = %s", (ch,))
        print("\ncleaned up throwaway channel")
    except Exception as exc:  # noqa: BLE001
        print(f"\n(cleanup skipped: {exc})")


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    asyncio.run(main(count))
