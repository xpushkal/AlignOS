# AlignOS

> Turn Slack chaos into verified team memory.

AlignOS is a Slack-native AI agent that turns messy team conversations into
structured, evidence-backed organizational memory. It detects decisions, extracts
project context, identifies conflicts, answers questions using live Slack
evidence, and maintains a verified memory layer for teams.

Unlike a normal Slack chatbot, AlignOS is designed to continuously observe project
conversations, detect meaningful events, ask for human confirmation when needed,
update a structured memory database, and warn teams when new messages contradict
previously confirmed decisions.

---

## Project Status

This repository currently holds the **complete product and engineering
documentation** for AlignOS. Application code has not been written yet — the docs
define the spec, architecture, data model, and a phased build plan so
implementation can begin cleanly.

**Committed stack:** Python + FastAPI · `slack_sdk` / Slack Bolt for Python ·
custom MCP server · Neon PostgreSQL · OpenRouter LLM.

### Documentation Map

| Doc | What's in it |
| --- | --- |
| [Docs/prd.md](Docs/prd.md) | Full Product Requirements Document (all 32 sections) |
| [Docs/ARCHITECTURE.md](Docs/ARCHITECTURE.md) | Components, backend↔MCP boundary, two-memory model, core flows |
| [Docs/DATA_MODEL.md](Docs/DATA_MODEL.md) | All 10 Neon Postgres tables, enums, indexes |
| [Docs/MCP_TOOLS.md](Docs/MCP_TOOLS.md) | The 8 MCP tools + LLM JSON contracts + guardrails |
| [Docs/API.md](Docs/API.md) | HTTP endpoints, Slack surface, scopes, signature verification |
| [Docs/SETUP.md](Docs/SETUP.md) | Local dev environment, env vars, Slack app config |
| [Docs/ROADMAP.md](Docs/ROADMAP.md) | 7-phase build plan + MVP checklist + demo script |
| [Docs/README.md](Docs/README.md) | Index of all docs |

**Getting started:** see [Docs/SETUP.md](Docs/SETUP.md), then follow the phases
in [Docs/ROADMAP.md](Docs/ROADMAP.md).

---

## Core Idea

Teams already make decisions in Slack, but those decisions get buried in channels,
threads, and files. AlignOS converts that unstructured conversation into a live,
verified project memory.

AlignOS combines:

- Slack app and agent experience
- Real-time Slack context retrieval
- RAG-based evidence verification
- MCP tools for decision, memory, and conflict operations
- A structured memory database for decisions, tasks, blockers, conflicts, and
  project state

## Target Users

- Hackathon teams that need fast decision tracking and demo-friendly workflows
- Startup and product teams making rapid decisions in Slack
- Engineering teams discussing technical decisions, bugs, deployments, and
  architecture
- Student project groups collaborating on assignments or software projects
- Managers, team leads, new joiners, and documentation owners who need reliable
  project context

## Key Features

### Evidence-Backed Question Answering

Users can ask questions such as:

```text
@AlignOS what did we decide about the database?
```

AlignOS searches confirmed memory and live Slack evidence before answering. If
evidence is weak or missing, it refuses to invent an answer.

### Automatic Decision Detection

AlignOS detects decision-like messages such as:

- "Let's finalize..."
- "We agreed on..."
- "Okay, we'll use..."
- "Let's go with..."
- "Deadline is fixed for..."

When a likely decision is found, AlignOS posts a Slack confirmation card with
actions to confirm, edit, or reject the decision.

### Live Memory Database

Confirmed project memory is stored in a structured database. Memory types include:

- Decisions
- Tasks
- Blockers
- Deadlines
- Unresolved questions
- Conflicts
- Project summaries

Each memory item includes evidence references and status metadata.

### Conflict Detection

AlignOS detects when a new message appears to contradict confirmed project memory.

Example:

```text
Confirmed memory: Database = PostgreSQL for v1
New message: I'll start MongoDB setup.
```

AlignOS can alert the team and offer actions such as reminding the decision,
reopening the decision, or ignoring the alert.

### Project Memory Summary

Users can ask:

```text
@AlignOS show project memory
```

AlignOS returns a skimmable summary of current goals, confirmed decisions, open
tasks, blockers, unresolved questions, recent conflicts, and upcoming deadlines.

### No-Evidence Refusal

If a user asks about something that was discussed but not confirmed, AlignOS
distinguishes between discussion and decision.

Example:

```text
I could not find enough evidence that pricing was finalized. I found discussion
about possible pricing options, but no confirmed decision.
```

## MVP Scope

The MVP is intended to include:

- Slack app mention support
- Slack message event listener
- Real-time Slack search retrieval
- MCP client connected to a custom MCP server
- Decision detection, decision saving, memory search
- Conflict detection and evidence verification
- Neon PostgreSQL memory database
- Slack confirmation and conflict-alert buttons
- Project memory summary command
- Evidence-backed Q&A

Full phase-by-phase plan in [Docs/ROADMAP.md](Docs/ROADMAP.md).

## Architecture (at a glance)

```text
Slack Workspace
  -> Slack App / Agent Interface
  -> FastAPI Backend Orchestrator
  -> Intent Router
  -> Real-Time Search API + Neon Memory DB
  -> MCP Client
  -> Custom MCP Server Tools
  -> LLM Reasoning Layer
  -> Slack Response / Card / Alert
```

Full detail in [Docs/ARCHITECTURE.md](Docs/ARCHITECTURE.md).

## Core MCP Tools

The custom MCP server exposes: `detect_decision`, `save_decision`,
`search_memory`, `detect_conflict`, `verify_evidence`, `generate_project_summary`,
`reopen_decision`, and `log_conflict_action`. The Slack backend handles Slack
events; the MCP server focuses on tools and reasoning operations. See
[Docs/MCP_TOOLS.md](Docs/MCP_TOOLS.md).

## Data Model

Planned database tables: `workspaces`, `channels`, `users`, `decisions`, `tasks`,
`blockers`, `conflicts`, `evidence_links`, `memory_items`, `audit_events`. Full
columns, enums, and indexes in [Docs/DATA_MODEL.md](Docs/DATA_MODEL.md).

## Security and Privacy Principles

- Verify Slack signing secrets for every request.
- Store tokens in environment variables.
- Use least-privilege Slack scopes.
- Ignore bot messages to prevent loops.
- Store memory objects and evidence references instead of full Slack history.
- Respect channel permissions; don't expose private-channel evidence to
  unauthorized users.
- Support channel-level opt-out and admin-controlled memory deletion.

## Product Positioning

AlignOS is a Slack-native agentic memory layer, not just a chatbot. It uses live
workspace context, confirmed memory, MCP tools, and evidence verification to help
teams stay aligned as decisions evolve.
