# AlignOS Roadmap & Build Plan

The phased path from empty repo to a demo-ready MVP, mapped to the committed
stack (Python/FastAPI + Supabase + MCP). Phases come from PRD §27; the MVP scope
from §10; post-MVP from §11; the acceptance target from §28 and §30.

Each phase has **deliverables** and a **success check** — don't move on until the
success check passes.

---

## Phase 1 — Slack Bot Foundation
**Deliverables**
- Slack app created and installed in a workspace
- FastAPI `/slack/events` endpoint with signature verification + URL challenge
- App-mention reply working
- Basic `/alignos help` (or mention-based help) working

**Success:** `@AlignOS hello` → the bot replies.

---

## Phase 2 — Memory Database (Supabase)
**Deliverables**
- Supabase project + Postgres connection wired
- `decisions` and `evidence_links` tables (migrations in `supabase/migrations/`)
- `search_memory` query function
- `save_decision` persistence function

**Success:** Backend can save and retrieve a test decision.

See [DATA_MODEL.md](DATA_MODEL.md) for the full schema.

---

## Phase 3 — MCP Server
**Deliverables**
- MCP server running; backend wired as MCP client
- Core MCP tools implemented: `detect_decision`, `save_decision`,
  `search_memory`, `detect_conflict`, `verify_evidence`

**Success:** Backend can call MCP tools and receive structured JSON.

See [MCP_TOOLS.md](MCP_TOOLS.md) for tool contracts.

---

## Phase 4 — Real-Time Search RAG
**Deliverables**
- Real-Time Search API integration (with fallback to channel history)
- Search query generator from user message
- Evidence formatter
- Evidence verification prompt (`verify_evidence` flow)

**Success:** `@AlignOS what did we decide about database?` → bot searches Slack
and answers with evidence + confidence + source.

---

## Phase 5 — Decision Confirmation Cards
**Deliverables**
- Decision detector on message events
- Slack Block Kit confirmation card (Confirm / Edit / Reject)
- Confirm/Reject handling at `/slack/interactions`
- Save confirmed decision to DB with evidence links

**Success:** "Let's finalize PostgreSQL for v1." → bot posts "Possible decision
detected" → user confirms → decision saved.

---

## Phase 6 — Conflict Detection
**Deliverables**
- Message topic extraction
- Memory comparison (`detect_conflict`)
- RTS latest-context check (avoid stale-memory false alarms)
- Conflict alert card (Remind / Reopen / Ignore) + `log_conflict_action`

**Success:** After confirming PostgreSQL, "I'll start MongoDB setup." → bot
detects the conflict and posts an alert.

---

## Phase 7 — Demo Polish
**Deliverables**
- Demo workspace + demo channel script
- Clean bot messages and Block Kit formatting
- Error handling and graceful fallbacks
- Short pitch + submission screenshots/video

**Success:** A judge can understand the product in under 2 minutes.

---

## MVP Scope Checklist (PRD §10)

- [ ] Slack app mention support
- [ ] Slack message event listener
- [ ] Real-Time Search API retrieval
- [ ] MCP client connected to custom MCP server
- [ ] Tools: `detect_decision`, `save_decision`, `search_memory`,
      `detect_conflict`, `verify_evidence`
- [ ] Supabase memory database
- [ ] Decision confirmation buttons
- [ ] Conflict alert buttons
- [ ] Project memory summary command
- [ ] Evidence-backed Q&A

---

## Final MVP Definition (PRD §30)

The MVP is complete when:

1. User can ask AlignOS questions in Slack.
2. AlignOS can search live Slack context.
3. AlignOS can detect a decision.
4. User can confirm the decision.
5. Confirmed decision is saved in memory.
6. AlignOS can answer future questions from memory + evidence.
7. AlignOS can detect a contradiction against confirmed memory.
8. AlignOS can show a project memory summary.

---

## Demo Acceptance Script (PRD §28)

The demo should walk through, in order:
1. **Messy discussion** — team debates PostgreSQL vs MongoDB.
2. **Decision detection** — bot proposes "Use PostgreSQL for v1", user confirms.
3. **Memory Q&A** — "@AlignOS why did we choose PostgreSQL?" → evidence-backed
   answer.
4. **Conflict** — "I'll start MongoDB setup." → bot flags the conflict.
5. **Project memory** — "@AlignOS show project memory" → skimmable summary.

Demo metrics to show (PRD §25.3): ≥1 detected decision, ≥1 confirmed memory item,
≥1 evidence-backed answer, ≥1 detected conflict, ≥1 no-evidence refusal.

---

## Post-MVP Backlog (PRD §11)

1. GitHub integration through MCP
2. Jira/Linear ticket creation
3. Notion/Google Docs decision export
4. Slack Canvas generation
5. Weekly decision digest
6. Multi-channel project graph
7. Web dashboard
8. Team analytics
9. Decision quality score
10. Automatic onboarding summary for new members

---

## Key Risks to Watch (PRD §26)

| Risk | Primary mitigation |
| --- | --- |
| Too many false conflict alerts | Alert only at medium/high confidence; Ignore button; suppress repeats |
| AI hallucination | RAG evidence checker; no-evidence refusal; confirmed memory as source of truth |
| Slack permission issues | Channel-history fallback; limit to installed channels |
| Overbuilding MCP | Keep Slack events in backend; start with 5 core tools |
| Privacy concerns | Store evidence references not full history; channel opt-out; admin controls |

See [ARCHITECTURE.md](ARCHITECTURE.md), [MCP_TOOLS.md](MCP_TOOLS.md), and the full
[prd.md](prd.md) for details.
