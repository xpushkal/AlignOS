# AlignOS Setup & Developer Onboarding

How to set up a local AlignOS development environment with the committed stack:
**Python + FastAPI**, **`slack_sdk` / Slack Bolt for Python**, a **custom MCP
server**, **Neon PostgreSQL**, and a pluggable **LLM provider**.

> **Status:** This is the intended setup for the codebase. No application code
> exists yet — this document describes the structure to build against (see
> [ROADMAP.md](ROADMAP.md) for the phased plan).

---

## 1. Prerequisites

- **Python 3.11+**
- A Python env/dependency manager — [`uv`](https://github.com/astral-sh/uv)
  (recommended) or Poetry, or `venv` + `pip`
- A **Neon** project (free tier is fine) — gives you a serverless Postgres
  `DATABASE_URL` connection string
- A **Slack app** with a workspace you can install it into
- **ngrok** (or similar) to expose your local server to Slack during development
- An **LLM API key** (Anthropic / OpenAI / other compatible provider)

---

## 2. Repository Layout

```text
AlignOS/
├── app/                    # FastAPI backend (Slack orchestrator)
│   ├── main.py             # FastAPI app + route registration
│   ├── config.py           # env/settings loading (pydantic-settings)
│   ├── slack/              # event/interaction/command handlers, signature verify
│   ├── flows/              # ask / decision / conflict flow handlers
│   ├── intent/             # intent router (rules + LLM fallback)
│   ├── rts/                # Real-Time Search client + caching
│   ├── mcp_client/         # MCP client wrapper (local-fallback transport)
│   ├── llm/                # LLM client + offline heuristic fallback
│   └── db/                 # Repository: Postgres (psycopg) + in-memory fallback
├── mcp_server/             # Custom MCP server
│   ├── core.py             # pure tool implementations (8 tools)
│   └── server.py           # MCP stdio wrapper (python -m mcp_server)
├── migrations/
│   └── 0001_init.sql       # Neon/Postgres schema
├── tests/                  # unit/integration tests, demo harness
├── .env.example            # template for required env vars
├── pyproject.toml          # tooling config
└── requirements.txt        # dependencies
```

---

## 3. Environment Variables

Create a `.env` from this template (and add `.env` to `.gitignore`):

```bash
# Slack
SLACK_BOT_TOKEN=xoxb-...            # Bot User OAuth token
SLACK_SIGNING_SECRET=...            # App Credentials → Signing Secret
SLACK_APP_TOKEN=xapp-...            # Only if using Socket Mode

# Neon PostgreSQL
DATABASE_URL=postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/alignos?sslmode=require

# LLM provider (use whichever provider you choose)
ANTHROPIC_API_KEY=...               # or OPENAI_API_KEY=...
LLM_MODEL=claude-opus-4-8           # default to the latest capable model

# App
APP_ENV=development
PORT=8000
```

> Never commit real secrets. Keep tokens in `.env` locally and in the deploy
> platform's secret store in production (PRD §14.3).

---

## 4. Install & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt    # or: uv pip install -r requirements.txt

# 2. Apply the schema to Neon
psql "$DATABASE_URL" -f migrations/0001_init.sql

# 3. Run the FastAPI backend
uvicorn app.main:app --reload --port 8000

# 4. Run the MCP server (separate process)
python -m mcp_server

# 5. Health check
curl http://localhost:8000/health
```

---

## 5. Slack App Configuration

In <https://api.slack.com/apps> create an app and configure:

1. **OAuth & Permissions → Scopes** — add the bot scopes from
   [API.md §3](API.md): `app_mentions:read`, `channels:history`, `chat:write`,
   `commands`, plus private-channel/history scopes where permitted. Apply least
   privilege.
2. **Event Subscriptions** — enable events, set the Request URL to
   `https://<your-ngrok>.ngrok.io/slack/events`, and subscribe to bot events:
   `app_mention`, `message.channels` (and `message.groups` if used). Slack will
   send a URL-verification challenge that your endpoint must echo back.
3. **Interactivity & Shortcuts** — enable and set the Request URL to
   `.../slack/interactions` (for Block Kit buttons/modals).
4. **Slash Commands** (optional) — create `/alignos` pointing at
   `.../slack/commands`.
5. **Install App** to your workspace to obtain the Bot User OAuth token
   (`SLACK_BOT_TOKEN`).

### 5.1 Expose your local server
```bash
ngrok http 8000
# Use the https URL ngrok prints as the base for all three Slack Request URLs.
```

---

## 6. First Smoke Test

This mirrors **Phase 1** in [ROADMAP.md](ROADMAP.md):

```text
In a channel where the bot is installed:
@AlignOS hello
→ the bot replies.
```

If that works, the event endpoint, signature verification, and reply path are all
wired correctly. Proceed through the roadmap phases from there.

---

## 7. Neon Notes

- Keep the `DATABASE_URL` server-side only; never ship it to a client. Use the
  **pooled** connection endpoint from the Neon dashboard for serverless workloads.
- Define the schema from [DATA_MODEL.md](DATA_MODEL.md) as forward-only
  migrations in `migrations/`; the initial schema is
  [../migrations/0001_init.sql](../migrations/0001_init.sql).
- The app uses a dependency-free in-memory store when `DATABASE_URL` is unset, so
  you can develop and run tests without Neon configured.
- All agent queries are scoped by `workspace_id` (and `channel_id` where
  relevant). Consider Postgres RLS keyed on `workspace_id` before exposing any
  access beyond the trusted backend role.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the big picture and
[ROADMAP.md](ROADMAP.md) for what to build first.
