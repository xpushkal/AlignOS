# AlignOS Deployment & Scaling

How to run AlignOS in production, from a single instance to a horizontally-scaled
fleet. Pair this with [SETUP.md](SETUP.md) (local dev) and [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Single instance (simplest)

Two ways to receive Slack events:

| Mode | Command | When |
| --- | --- | --- |
| **Socket Mode** | `python -m app.socket_mode` | Local / single instance; no public URL needed |
| **HTTP events** | `uvicorn app.main:api --port 8000` | Behind a public URL / load balancer |

Required env (see [.env.example](../.env.example)): `SLACK_BOT_TOKEN`,
`SLACK_SIGNING_SECRET` (HTTP mode), `SLACK_APP_TOKEN` (Socket Mode),
`DATABASE_URL` (Neon), `OPENROUTER_API_KEY`.

Apply the schema once: `psql "$DATABASE_URL" -f migrations/0001_init.sql`.

A single instance already handles real load well thanks to:
- **LLM pre-gating** — most messages never hit the model (ARCHITECTURE §2.4a)
- **Bounded concurrency** — `MAX_CONCURRENCY` parallelism, excess queued in-loop
- **Connection pooling** — `DB_POOL_MAX_SIZE` reused Neon connections
- **Answer cache** — repeated questions served without the LLM

Tune `MAX_CONCURRENCY` and `DB_POOL_MAX_SIZE` together (keep pool ≥ concurrency).

---

## 2. Multiple instances (horizontal scale)

When one instance isn't enough, run several **stateless** replicas:

1. **Use HTTP events**, not Socket Mode. Point the Slack app's
   *Event Subscriptions → Request URL* at `https://<lb>/slack/events` and
   *Interactivity → Request URL* at `https://<lb>/slack/interactions`.
2. Put the replicas behind a **load balancer**.
3. Set **`REDIS_URL`** on every replica. This is what makes them safe to scale:
   rate limiting, event-dedup, and the answer cache become **shared** (see
   [app/store.py](../app/store.py)). Without it, each replica keeps its own
   counters → double-processing and inconsistent limits.

```text
            Slack  ──►  Load Balancer  ──►  AlignOS replica 1 ─┐
                                       ──►  AlignOS replica 2 ─┼─► Neon (pooled)
                                       ──►  AlignOS replica N ─┘   Redis (shared)
                                                                   OpenRouter
```

Checklist per replica: same `DATABASE_URL`, same `REDIS_URL`, same Slack creds,
HTTP mode. Verify with `GET /health` — it reports `store_backend: redis`,
`db_backend`, `inflight`, and `max_concurrency`.

---

## 3. Capacity & tuning

- **DB:** use Neon's **pooled** connection endpoint; size `DB_POOL_MAX_SIZE`
  per replica so `replicas × pool_size` stays under Neon's connection limit.
- **LLM:** OpenRouter rate limits are the usual ceiling. `MAX_CONCURRENCY` caps
  concurrent calls per replica; total in flight ≈ `replicas × MAX_CONCURRENCY`.
- **Rate limits:** `RATE_LIMIT_MAX_CALLS` / `RATE_LIMIT_WINDOW_SECONDS` are
  enforced globally once `REDIS_URL` is set.

### Measure before optimizing
Run the load test to see real throughput/latency and how few requests actually
reach the LLM (gating + cache):

```bash
python scripts/loadtest.py 50      # 50 concurrent Q&A requests
```

It reports p50/p95 latency, throughput, and LLM-call count, and cleans up after
itself. Use it to decide whether you need the next steps.

---

## 4. Further scaling (only if the load test shows a bottleneck)

These are intentionally **not** implemented yet — they add operational complexity
and, after gating + caching, usually aren't needed at small-team scale:

- **Durable ack-and-queue** (Redis Streams / Celery / RQ) with a separate worker
  pool — for spike buffering and at-least-once processing across restarts.
- **Per-channel batching** — coalesce bursty messages in a channel into one LLM
  call (trades instant decision cards for fewer calls).

See [ARCHITECTURE.md](ARCHITECTURE.md) §2.4a for where these would slot in.
