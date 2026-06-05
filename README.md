# AlignOS

Turn Slack chaos into verified team memory.

AlignOS is a Slack-native AI agent that turns messy team conversations into structured, evidence-backed organizational memory. It detects decisions, extracts project context, identifies conflicts, answers questions using live Slack evidence, and maintains a verified memory layer for teams.

Unlike a normal Slack chatbot, AlignOS is designed to continuously observe project conversations, detect meaningful events, ask for human confirmation when needed, update a structured memory database, and warn teams when new messages contradict previously confirmed decisions.

## Project Status

This repository currently contains the product requirements document for AlignOS:

- `Docs/Product Requirements Document.pdf`

Implementation files are not included yet. The README below summarizes the intended product, MVP scope, architecture, and build plan from the PRD.

## Core Idea

Teams already make decisions in Slack, but those decisions get buried in channels, threads, and files. AlignOS converts that unstructured conversation into a live, verified project memory.

AlignOS combines:

- Slack app and agent experience
- Real-time Slack context retrieval
- RAG-based evidence verification
- MCP tools for decision, memory, and conflict operations
- A structured memory database for decisions, tasks, blockers, conflicts, and project state

## Target Users

- Hackathon teams that need fast decision tracking and demo-friendly workflows
- Startup and product teams making rapid decisions in Slack
- Engineering teams discussing technical decisions, bugs, deployments, and architecture
- Student project groups collaborating on assignments or software projects
- Managers, team leads, new joiners, and documentation owners who need reliable project context

## Key Features

### Evidence-Backed Question Answering

Users can ask questions such as:

```text
@AlignOS what did we decide about the database?
```

AlignOS searches confirmed memory and live Slack evidence before answering. If evidence is weak or missing, it refuses to invent an answer.

### Automatic Decision Detection

AlignOS detects decision-like messages such as:

- "Let's finalize..."
- "We agreed on..."
- "Okay, we'll use..."
- "Let's go with..."
- "Deadline is fixed for..."

When a likely decision is found, AlignOS posts a Slack confirmation card with actions to confirm, edit, or reject the decision.

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

AlignOS can alert the team and offer actions such as reminding the decision, reopening the decision, or ignoring the alert.

### Project Memory Summary

Users can ask:

```text
@AlignOS show project memory
```

AlignOS returns a skimmable summary of current goals, confirmed decisions, open tasks, blockers, unresolved questions, recent conflicts, and upcoming deadlines.

### No-Evidence Refusal

If a user asks about something that was discussed but not confirmed, AlignOS distinguishes between discussion and decision.

Example:

```text
I could not find enough evidence that pricing was finalized. I found discussion about possible pricing options, but no confirmed decision.
```

## MVP Scope

The MVP is intended to include:

- Slack app mention support
- Slack message event listener
- Real-time Slack search retrieval
- MCP client connected to a custom MCP server
- Decision detection
- Decision saving
- Memory search
- Conflict detection
- Evidence verification
- PostgreSQL or Supabase memory database
- Slack confirmation buttons
- Slack conflict alert buttons
- Project memory summary command
- Evidence-backed Q&A

## Suggested Architecture

```text
Slack Workspace
  -> Slack App / Agent Interface
  -> Backend Orchestrator
  -> Intent Router
  -> Real-Time Search API + Memory DB
  -> MCP Client
  -> Custom MCP Server Tools
  -> LLM Reasoning Layer
  -> Slack Response / Card / Alert
```

## Suggested Tech Stack

### Slack Interface

- Slack app
- Slack Block Kit
- App mentions
- Message events
- Buttons and modals
- Optional slash commands

### Backend

Preferred:

- Node.js
- Slack Bolt SDK
- Express or Fastify

Alternative:

- Python
- FastAPI
- Slack SDK

### AI Layer

- LLM provider such as OpenAI, Anthropic, or another compatible model provider
- Structured JSON outputs
- RAG evidence verification prompts
- Guardrails for no-evidence refusal

### MCP Layer

- Custom MCP server
- MCP client in the backend
- Tools for memory, decision detection, conflict detection, and evidence verification

### Database

- Supabase PostgreSQL
- Plain PostgreSQL
- SQLite for local demos only

### Deployment

- Render
- Railway
- Fly.io
- ngrok for local Slack testing

## Core MCP Tools

The custom MCP server should expose:

- `detect_decision`
- `save_decision`
- `search_memory`
- `detect_conflict`
- `verify_evidence`
- `generate_project_summary`
- `reopen_decision`
- `log_conflict_action`

The Slack backend should handle Slack events. The MCP server should focus on tools and reasoning operations.

## Data Model

Planned database tables include:

- `workspaces`
- `channels`
- `users`
- `decisions`
- `tasks`
- `blockers`
- `conflicts`
- `evidence_links`
- `memory_items`
- `audit_events`

Decision statuses:

- `proposed`
- `confirmed`
- `rejected`
- `reopened`
- `superseded`

Conflict statuses:

- `open`
- `ignored`
- `resolved`
- `reopened_decision`

## Main Flows

### Ask a Question

1. User mentions AlignOS in Slack.
2. Backend verifies the Slack request.
3. Intent router classifies the message.
4. Backend searches confirmed memory.
5. Backend retrieves relevant live Slack evidence.
6. Evidence verification checks support.
7. LLM generates a grounded answer.
8. AlignOS replies in Slack.

### Detect a Decision

1. User sends a decision-like message.
2. Backend retrieves nearby context.
3. MCP tool analyzes the message and context.
4. AlignOS posts a confirmation card.
5. User confirms, edits, or rejects.
6. Confirmed decisions are saved to memory with evidence references.

### Detect a Conflict

1. User sends a new message.
2. Backend checks related memory.
3. Latest Slack context is retrieved if needed.
4. Conflict detection compares the new message with confirmed memory.
5. AlignOS posts a conflict alert when confidence is sufficient.
6. User chooses to remind, reopen, or ignore.

## API Endpoints

Planned backend endpoints:

- `POST /slack/events`
- `POST /slack/interactions`
- `POST /slack/commands`
- `POST /agent/ask`
- `POST /agent/detect-decision`
- `POST /agent/detect-conflict`
- `GET /health`

## Security and Privacy Principles

- Verify Slack signing secrets for every request.
- Store tokens in environment variables.
- Use least-privilege Slack scopes.
- Ignore bot messages to prevent loops.
- Avoid storing full Slack history for the MVP.
- Store memory objects and evidence references instead.
- Respect channel permissions.
- Do not expose private-channel evidence to unauthorized users.
- Support channel-level opt-out and admin-controlled memory deletion.

## MVP Build Plan

1. Slack bot foundation
2. Memory database setup
3. MCP server and core tools
4. Real-time search and RAG evidence verification
5. Decision confirmation cards
6. Conflict detection
7. Demo polish

## Demo Scenario

1. A team discusses PostgreSQL vs MongoDB in Slack.
2. The team finalizes PostgreSQL for v1.
3. AlignOS detects the decision and asks for confirmation.
4. A user confirms the decision.
5. Another user asks why PostgreSQL was chosen.
6. AlignOS answers using confirmed memory and Slack evidence.
7. A user later mentions starting MongoDB setup.
8. AlignOS detects the conflict and posts an alert.

## Success Metrics

- Decisions detected
- Decision confirmation rate
- Conflicts detected
- Useful answers generated
- No-evidence refusals
- Reduction in repeated questions
- Decision detection precision
- Conflict detection precision
- Hallucination rate
- User feedback score

## Documentation

The full product requirements document is available at:

- `Docs/Product Requirements Document.pdf`

## Product Positioning

AlignOS is a Slack-native agentic memory layer, not just a chatbot. It uses live workspace context, confirmed memory, MCP tools, and evidence verification to help teams stay aligned as decisions evolve.
# AlignOS
