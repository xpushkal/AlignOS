# AlignOS Setup & Developer Onboarding

How to set up a local AlignOS development environment with the committed stack:
**Python + FastAPI**, **`slack_sdk` / Slack Bolt for Python**, a **custom MCP
server**, **Supabase PostgreSQL**, and a pluggable **LLM provider**.

> **Status:** This is the intended setup for the codebase. No application code
> exists yet — this document describes the structure to build against (see
> [ROADMAP.md](ROADMAP.md) for the phased plan).

---

## 1. Prerequisites

- **Python 3.11+**
- A Python env/dependency manager — [`uv`](https://github.com/astral-sh/uv)
  (recommended) or Poetry, or `venv` + `pip`
- A **Supabase** project (free tier is fine) — gives you a hosted Postgres + keys
- A **Slack app** with a workspace you can install it into
- **ngrok** (or similar) to expose your local server to Slack during development
- An **LLM API key** (Anthropic / OpenAI / other compatible provider)

---

## 2. Suggested Repository Layout

This is the target structure for implementation (not yet created):

```text
AlignOS/
├── app/                    # FastAPI backend (Slack orchestrator)
│   ├── main.py             # FastAPI app + route registration
│   ├── slack/              # event/interaction/command handlers, signature verify
│   ├── flows/              # ask / decision / conflict flow handlers
│   ├── intent/             # intent router (rules + LLM fallback)
│   ├── rts/                # Real-Time Search client + caching
│   ├── mcp_client/         # MCP client wrapper
│   ├── db/                 # Supabase client + queries
│   └── config.py           # env/settings loading
├── mcp_server/             # Custom MCP server (the 8 tools)
│   └── tools/              # detect_decision, save_decision, ... one per file
├── supabase/
│   └── migrations/         # SQL migrations for the data model
├── tests/                  # unit/integration tests, demo harness
├── .env.example            # template for required env vars
├── pyproject.toml          # deps (or requirements.txt)
└── README.md
```

---

## 3. Environment Variables

Create a `.env` from this template (and add `.env` to `.gitignore`):

```bash
# Slack
SLACK_BOT_TOKEN=xoxb-...            # Bot User OAuth token
SLACK_SIGNING_SECRET=...            # App Credentials → Signing Secret
SLACK_APP_TOKEN=xapp-...            # Only if using Socket Mode

# Supabase
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=...            # Service role key (server-side only, secret)
DATABASE_URL=postgresql://...       # Direct Postgres connection (for migrations)

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
# 1. Install dependencies (uv example)
uv sync                # or: pip install -r requirements.txt

# 2. Apply database migrations to Supabase
supabase db push       # or run SQL in supabase/migrations/ via the dashboard

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

## 7. Supabase Notes

- Use the **service role key** server-side only; never ship it to a client.
- Define the schema from [DATA_MODEL.md](DATA_MODEL.md) as forward-only
  migrations in `supabase/migrations/`.
- All agent queries are scoped by `workspace_id` (and `channel_id` where
  relevant). Consider RLS keyed on `workspace_id` before exposing any
  non-service-role access.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the big picture and
[ROADMAP.md](ROADMAP.md) for what to build first.
