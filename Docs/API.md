# AlignOS API & Slack Surface

This document covers the backend HTTP endpoints, the Slack interaction surface
(mentions, slash commands, Block Kit cards), and the required Slack scopes.

---

## 1. Backend HTTP Endpoints (PRD §22)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/slack/events` | App mentions, message events, and Slack URL verification challenge |
| POST | `/slack/interactions` | Button clicks and modal submissions |
| POST | `/slack/commands` | Optional slash commands |
| POST | `/agent/ask` | Internal endpoint for question-answering |
| POST | `/agent/detect-decision` | Internal endpoint for decision detection |
| POST | `/agent/detect-conflict` | Internal endpoint for conflict detection |
| GET | `/health` | Health check |

### 1.1 Slack-facing endpoints
`/slack/events`, `/slack/interactions`, and `/slack/commands` are called by Slack.
They must:
- **Verify the Slack signing secret** on every request (see §4).
- **Answer the URL-verification challenge** on `/slack/events` (echo the
  `challenge` value when `type == "url_verification"`).
- **Acknowledge within Slack's response window** (~3s), then do heavy work
  asynchronously.
- **De-duplicate** by Slack `event_id` (idempotency).
- **Ignore bot messages** to prevent loops.

### 1.2 Internal `/agent/*` endpoints
`/agent/ask`, `/agent/detect-decision`, and `/agent/detect-conflict` expose the
core flows for testing and internal orchestration. They take normalized JSON
(message, context, scope) and return the same structured JSON the LLM/MCP layer
produces — useful for unit tests and the demo harness without going through
Slack.

### 1.3 `/health`
Returns 200 with basic status (and, ideally, DB + MCP reachability) for uptime
checks on the deploy target (Render / Railway / Fly.io).

---

## 2. Slack Interaction Surface

### 2.1 App Mentions (PRD §21.1)
```text
@AlignOS what did we decide about database?
@AlignOS show project memory
@AlignOS summarize today
@AlignOS show conflicts
@AlignOS reopen database decision
```

### 2.2 Optional Slash Commands (PRD §21.2)
```text
/alignos memory
/alignos decisions
/alignos conflicts
/alignos summarize
/alignos help
```

### 2.3 Block Kit Cards & Buttons (PRD §13.6, §21.3)

| Card | Buttons / Actions |
| --- | --- |
| **Decision confirmation** | `Confirm`, `Edit`, `Reject` |
| **Conflict alert** | `Remind Decision`, `Reopen Decision`, `Ignore` |
| **Memory item** | `View Details`, `Export`, `Update`, `Archive` |
| **Insufficient evidence** | `Start Decision Thread`, `Search Again`, `Ignore` |

Button clicks arrive at `/slack/interactions`. The handler maps each action to the
relevant MCP tool (e.g. `Confirm` → `save_decision`, conflict actions →
`log_conflict_action`, `Reopen Decision` → `reopen_decision`).

---

## 3. Slack Scopes & Permissions (PRD §24)

Likely Slack capabilities needed:

- Read app mentions (`app_mentions:read`)
- Read messages in channels where installed (`channels:history`, and
  `groups:history` for private channels where permitted)
- Post messages (`chat:write`)
- Use interactivity (buttons/modals)
- Use AI assistant / app features
- Use Real-Time Search API if available
- Optional slash commands (`commands`)

> Exact scopes depend on the Slack app configuration and workspace access. Apply
> **least privilege** (PRD §14.3) — request only what the enabled features need.

Event subscriptions to enable: `app_mention`, and `message.channels` (plus
`message.groups` for private channels where permitted).

---

## 4. Request Verification

Every Slack-facing request must be verified before processing (PRD §14.3):

1. Read the `X-Slack-Signature` and `X-Slack-Request-Timestamp` headers.
2. Reject requests with a stale timestamp (replay protection).
3. Compute the HMAC-SHA256 of `v0:{timestamp}:{raw_body}` using
   `SLACK_SIGNING_SECRET` and compare (constant-time) against the signature.

`slack_sdk` / Slack Bolt provides a `SignatureVerifier` and built-in middleware
that handles this — prefer it over a hand-rolled check.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how these endpoints fit the flows,
[MCP_TOOLS.md](MCP_TOOLS.md) for the tools they invoke, and [SETUP.md](SETUP.md)
for wiring the Slack app to these URLs.
