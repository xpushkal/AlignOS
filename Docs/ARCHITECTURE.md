# AlignOS Architecture

This document describes how AlignOS is structured: its components, the boundary
between the Slack backend and the MCP server, the two-layer memory model, and the
three core runtime flows.

> **Committed stack:** Python + FastAPI backend, `slack_sdk` / Slack Bolt for
> Python, a custom MCP server, Supabase PostgreSQL, and a pluggable LLM provider.

---

## 1. Component Overview

```text
                          ┌─────────────────────┐
                          │   Slack Workspace    │
                          │  (channels, threads) │
                          └──────────┬──────────┘
                                     │ events, mentions, button clicks
                                     ▼
                          ┌─────────────────────┐
                          │  Slack App / Agent   │   slack_sdk / Bolt
                          │      Interface       │   Block Kit cards
                          └──────────┬──────────┘
                                     │
                                     ▼
        ┌────────────────────────────────────────────────────┐
        │            FastAPI Backend Orchestrator             │
        │  ┌──────────────┐   ┌──────────────────────────┐    │
        │  │ Intent Router │──▶│  Flow handlers:          │    │
        │  └──────────────┘   │  ask / decision / conflict│   │
        │                     └────────────┬─────────────┘    │
        └───────────────┬──────────────────┼─────────────────┘
                        │                  │
          ┌─────────────▼──────┐    ┌──────▼───────────────┐
          │ Real-Time Search   │    │     MCP Client        │
          │ API (live context) │    └──────┬───────────────┘
          └────────────────────┘           │ MCP protocol
                        ▲                   ▼
                        │          ┌─────────────────────┐
          ┌─────────────┴────┐     │  Custom MCP Server   │
          │  Supabase         │◀───▶│  (8 reasoning tools) │
          │  Memory Database  │     └──────────┬──────────┘
          └───────────────────┘                │
                                                ▼
                                     ┌─────────────────────┐
                                     │  LLM Reasoning Layer │
                                     └──────────┬──────────┘
                                                │
                                                ▼
                                     ┌─────────────────────┐
                                     │  Slack Response /    │
                                     │  Card / Alert        │
                                     └─────────────────────┘
```

---

## 2. Components and Responsibilities

### 2.1 Slack App / Agent Interface
- Receives events (app mentions, channel messages, thread replies), interactive
  payloads (button clicks, modal submissions), and slash commands.
- Renders Block Kit cards: decision confirmation, conflict alert, memory
  summary, insufficient-evidence prompt.
- Built with `slack_sdk` / Slack Bolt for Python.

### 2.2 FastAPI Backend Orchestrator
The central nervous system. Owns:
- **Request verification** — validates the Slack signing secret on every request
  and answers the Slack URL-verification challenge.
- **Idempotency** — de-duplicates events by Slack `event_id` so retries don't
  create duplicate memory items.
- **Intent Router** — classifies each inbound message into an intent
  (`question_answering`, `possible_decision`, `possible_conflict`, `show_memory`,
  `save_task`, `summarize_thread`, `unknown`) using rule-based checks first, then
  an LLM fallback for ambiguous cases. Returns structured JSON with a confidence
  score.
- **Flow handlers** — the Ask / Decision / Conflict flows (see §4).
- **Async processing** — acknowledges Slack within its response window, then does
  the heavy LLM/RTS/MCP work asynchronously.

### 2.3 Real-Time Search (RTS) API
- Pulls **live Slack context**: latest messages, recent decisions, thread
  context, files, relevant channel history.
- Used for answering questions, verifying decisions, checking conflicts, and
  summarizing recent changes.
- Calls are minimized and cached where appropriate. If RTS is unavailable, the
  backend falls back to channel history in installed channels.

### 2.4 MCP Client (in backend) ↔ Custom MCP Server
- The backend acts as an **MCP client**; the MCP server exposes the reasoning and
  memory tools.
- **Boundary rule (PRD §23, §26.4):** Slack event handling stays in the FastAPI
  backend. The MCP server never touches Slack events — it only exposes tools.
- The MCP server exposes 8 tools — see [MCP_TOOLS.md](MCP_TOOLS.md):
  `detect_decision`, `save_decision`, `search_memory`, `detect_conflict`,
  `verify_evidence`, `generate_project_summary`, `reopen_decision`,
  `log_conflict_action`.

### 2.5 LLM Reasoning Layer
- Provider-pluggable (OpenAI / Anthropic / other). Default to the latest, most
  capable model for the chosen provider.
- Produces **structured JSON** for classification, detection, and verification.
- Bound by the no-hallucination guardrails in [MCP_TOOLS.md](MCP_TOOLS.md) and
  PRD §19: refuse without evidence, separate "confirmed" from "discussed", prefer
  latest confirmed memory.

### 2.6 Supabase Memory Database
- The **verified, long-term memory layer**. Stores confirmed decisions, tasks,
  blockers, conflicts, evidence references, and project summaries.
- Workspace/channel scoped. See [DATA_MODEL.md](DATA_MODEL.md).

---

## 3. Two-Layer Memory Model

AlignOS's intelligence comes from combining two distinct memory sources
(PRD §7):

| Layer | Source | Nature | Used for |
| --- | --- | --- | --- |
| **Live Slack Context** | Real-Time Search API | Raw, fresh, unstructured | Latest messages, thread context, recent discussion, evidence retrieval |
| **Verified Memory** | Supabase database | Clean, structured, long-term | Confirmed decisions, tasks, blockers, conflicts, summaries |

Answers and conflict checks fuse both: confirmed memory is the source of truth,
and live context provides freshness and supporting evidence.

---

## 4. Core Runtime Flows

### 4.1 Ask-Question Flow
```text
@AlignOS why did we choose PostgreSQL?
```
1. Slack sends an app-mention event to `POST /slack/events`.
2. Backend verifies the Slack signature and acknowledges the event.
3. Intent Router classifies it as `question_answering`.
4. Backend queries the memory DB (`search_memory`) for the topic.
5. Backend calls the RTS API for live Slack evidence.
6. Backend calls `verify_evidence` to check support level.
7. LLM generates an answer **using only verified context**.
8. Backend posts the answer (with confidence + source) to the thread.

### 4.2 Decision-Detection Flow
```text
Okay final, PostgreSQL for v1.
```
1. Slack sends a message event.
2. Backend ignores bot messages (loop prevention).
3. Backend retrieves nearby thread/channel context.
4. Backend calls `detect_decision`.
5. If confidence is high enough, backend posts a decision confirmation card
   (Confirm / Edit / Reject).
6. User clicks **Confirm** → `POST /slack/interactions`.
7. Backend calls `save_decision`.
8. Decision is stored in Supabase with evidence links.
9. Bot posts "Decision saved."

### 4.3 Conflict-Detection Flow
```text
I'll start MongoDB setup.
```
1. Slack sends a message event.
2. Backend extracts the topic (e.g. "database").
3. Backend searches memory for related decisions → finds the PostgreSQL decision.
4. Backend optionally calls RTS to check whether a newer message changed the
   decision.
5. Backend calls `detect_conflict` (new message vs. memory vs. latest context).
6. If a conflict is detected with sufficient confidence, bot posts an alert card
   (Remind Decision / Reopen Decision / Ignore).
7. User chooses an action; the choice is recorded via `log_conflict_action`.

---

## 5. Cross-Cutting Concerns

- **Performance:** ack Slack within its window; run LLM/RTS work async; cache RTS;
  keep simple memory queries fast.
- **Reliability:** idempotent events, graceful LLM/MCP fallbacks, MCP failures
  must not crash the Slack app, clear DB-failure logging.
- **Security:** verify signing secret on every request, secrets in env vars,
  least-privilege scopes, store evidence references (not full history).
- **Privacy:** respect channel access, no private-channel evidence to
  unauthorized users, channel-level opt-out, admin delete-memory control.
- **Explainability:** every important answer shows confidence, source
  (confirmed memory vs. live search), evidence sufficiency, and whether conflicts
  exist.

See [DATA_MODEL.md](DATA_MODEL.md), [MCP_TOOLS.md](MCP_TOOLS.md),
[API.md](API.md), [SETUP.md](SETUP.md), and [ROADMAP.md](ROADMAP.md) for details.
