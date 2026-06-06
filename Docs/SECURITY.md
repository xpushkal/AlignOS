# AlignOS Security

This document records the security review of the AlignOS backend, the mitigations
in place, and how to configure them. It also clarifies the difference between two
concerns that are often conflated: **rate limiting** and **prompt injection**.

> **Rate limiting** bounds how often a user/IP can trigger work — it protects
> against abuse, cost blow-ups, and denial of service. It does **not** by itself
> stop prompt injection; it only limits how often an attacker can attempt it.
>
> **Prompt injection** is when untrusted text tries to override the model's
> instructions. It is mitigated by *isolating* untrusted content and instructing
> the model to treat it as data — see §2.

---

## 1. Review Findings & Status

| # | Issue | Severity | Status | Mitigation |
| --- | --- | --- | --- | --- |
| V1 | No rate limiting (abuse / cost / DoS) | High | Fixed | Per-user (Slack) and per-IP (`/agent/*`) sliding-window limiter |
| V2 | Prompt injection via undelimited user text | High | Fixed | Fenced untrusted content + system guard ([app/llm/client.py](../app/llm/client.py)) |
| V3 | `/agent/*` endpoints unauthenticated | High | Fixed | Optional `X-AlignOS-Token` shared-secret (`AGENT_API_TOKEN`) |
| V4 | Raw exception text returned to users | Medium | Fixed | `mcp_client` returns a generic `internal_tool_error` |
| V5 | Slack mrkdwn / notification injection (`<!channel>`) | Medium | Fixed | `escape_slack` on all user-controlled card text |
| V6 | No input length cap (oversized prompts) | Medium | Fixed | `sanitize_text` truncates to `MAX_INPUT_CHARS` |
| V7 | Malformed 503 on unconfigured `/slack/*` | Low | Fixed | Proper `JSONResponse(status_code=503)` |

**Verified safe (no change needed):**
- **SQL injection** — all queries in [app/db/postgres_repo.py](../app/db/postgres_repo.py)
  use psycopg parameter binding (`%s` / named params); user input is never
  interpolated into SQL strings.
- **Slack request authenticity** — handled by Slack Bolt's signing-secret
  verification on `/slack/*`.
- **Secrets** — `.env` is gitignored; only `.env.example` (placeholders) is tracked.

---

## 2. Prompt-Injection Defenses

Implemented in [app/security.py](../app/security.py) and
[app/llm/client.py](../app/llm/client.py):

1. **Sanitize** every piece of user content (`sanitize_text`): strip control
   characters, remove attempts to spoof the fence markers, and truncate to
   `MAX_INPUT_CHARS`.
2. **Fence** untrusted content (`wrap_untrusted`) inside
   `<<<UNTRUSTED_INPUT>>> … <<<END_UNTRUSTED_INPUT>>>` markers before it enters
   any prompt.
3. **Guard** the model with a system instruction: treat everything inside the
   fence as data, never as instructions, and never reveal/modify the system
   prompt.
4. **Guardrails downstream** — answers still pass `verify_evidence`; unsupported
   claims trigger the no-evidence refusal (PRD §9.6, §19), so a successful
   injection still cannot fabricate confirmed memory.
5. **Heuristic fallback** — when no LLM key is set, detection/verification run on
   deterministic rules that have no instructions to hijack.

> Note: prompt-injection defense is defense-in-depth, not a guarantee. Keep the
> model's authority low — AlignOS never executes actions from message content
> without explicit human confirmation (PRD §6, non-goal #4).

---

## 3. Rate Limiting

A sliding-window `RateLimiter` ([app/security.py](../app/security.py)) bounds:

- **Slack users** — keyed by `workspace:user`. App mentions over the limit get a
  brief "slow down" reply; passive message scanning drops silently to avoid
  amplification.
- **`/agent/*` callers** — keyed by client IP, enforced by the `agent_guard`
  dependency.

Configure via env (see [.env.example](../.env.example)):

| Var | Default | Meaning |
| --- | --- | --- |
| `RATE_LIMIT_MAX_CALLS` | `20` | Max calls per window per key |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length |
| `MAX_INPUT_CHARS` | `4000` | Max chars accepted from a single message |

> The limiter defaults to **in-process** state. Set `REDIS_URL` to share rate
> limits, event-dedup, and the answer cache across multiple instances (see
> [ARCHITECTURE.md](ARCHITECTURE.md) §2.4a) — required when running more than one
> replica behind a load balancer.

---

## 4. Endpoint Authentication

- `/slack/*` — authenticated by Slack signing-secret verification (Bolt).
- `/agent/*` — internal endpoints. Set `AGENT_API_TOKEN` to require an
  `X-AlignOS-Token` header; requests without the correct token get `401`. Leave
  it unset only for trusted local development.
- `/health` — unauthenticated by design (liveness probe); returns no secrets.

---

## 5. Operational Recommendations

- Apply **least-privilege** Slack scopes (see [API.md §3](API.md)).
- Keep `DATABASE_URL`, `OPENROUTER_API_KEY`, and `AGENT_API_TOKEN` in the deploy
  platform's secret store, never in git.
- Run behind TLS (the deploy targets in [SETUP.md](SETUP.md) provide it).
- Consider Postgres Row-Level Security keyed on `workspace_id` before exposing
  any access beyond the trusted backend role ([DATA_MODEL.md §1](DATA_MODEL.md)).
- Rotate the OpenRouter key and `AGENT_API_TOKEN` periodically.
