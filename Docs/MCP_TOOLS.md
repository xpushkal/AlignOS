# AlignOS MCP Tools & LLM Contracts

AlignOS runs a **custom MCP server** that exposes reasoning and memory operations
as tools. The FastAPI backend is the **MCP client**. The MCP server never handles
Slack events — that boundary stays in the backend (PRD §23, §26.4).

This document specifies the 8 tools, their input/output contracts, the 3 LLM
prompt JSON contracts, and the no-hallucination guardrails.

---

## 1. Tool Catalog

| # | Tool | Purpose |
| --- | --- | --- |
| 1 | `detect_decision` | Decide whether a message + context constitutes a decision |
| 2 | `save_decision` | Persist a confirmed decision to the memory DB |
| 3 | `search_memory` | Retrieve relevant memory items by topic/scope |
| 4 | `detect_conflict` | Compare a new message against confirmed memory |
| 5 | `verify_evidence` | Check whether a proposed answer is supported by evidence |
| 6 | `generate_project_summary` | Produce a skimmable project memory summary |
| 7 | `reopen_decision` | Move a confirmed decision to `reopened` |
| 8 | `log_conflict_action` | Record the user's choice on a conflict alert |

The first 5 are the MVP core (PRD §10); tools 6–8 round out the full feature set
(PRD §23).

---

## 2. Tool Contracts

### 2.1 `detect_decision`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `message` | The triggering Slack message text |
| Input | `thread_context` | Messages in the same thread |
| Input | `recent_channel_context` | Recent nearby channel messages |
| Output | `is_decision` | boolean |
| Output | `title` | Short decision title |
| Output | `summary` | What was decided |
| Output | `reason` | Why |
| Output | `participants` | Users involved |
| Output | `confidence` | 0–1 |
| Output | `evidence_ids` | Slack message references supporting the decision |

### 2.2 `save_decision`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `decision` | Decision object (title, summary, reason, evidence) |
| Input | `workspace_id` | Scope |
| Input | `channel_id` | Scope |
| Input | `confirmed_by` | Slack user who confirmed |
| Output | `decision_id` | New row ID |
| Output | `status` | Resulting status (`confirmed`) |

### 2.3 `search_memory`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `query` | Topic / natural-language query |
| Input | `workspace_id` | Scope |
| Input | `channel_id` | Scope |
| Output | `memory_items` | Matching memory items (with status + confidence) |

### 2.4 `detect_conflict`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `new_message` | The message to check |
| Input | `relevant_memory` | Memory items on the same topic |
| Input | `recent_context` | Latest Slack context (in case memory is stale) |
| Output | `is_conflict` | boolean |
| Output | `conflict_type` | e.g. `technology_choice` |
| Output | `explanation` | Why it conflicts |
| Output | `conflicting_memory_id` | The contradicted memory item |
| Output | `severity` | `low` / `medium` / `high` |

### 2.5 `verify_evidence`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `proposed_answer` | Draft answer to validate |
| Input | `evidence_messages` | Retrieved Slack evidence |
| Input | `memory_items` | Relevant confirmed memory |
| Output | `support_level` | `SUPPORTED` / `PARTIALLY_SUPPORTED` / `CONFLICTING` / `INSUFFICIENT_EVIDENCE` |
| Output | `missing_evidence` | What's not backed |
| Output | `contradictions` | Conflicting facts found |
| Output | `final_confidence` | 0–1 |

### 2.6 `generate_project_summary`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `workspace_id`, `channel_id` | Scope |
| Output | Structured summary | current goal, confirmed decisions, open tasks, blockers, unresolved questions, recent conflicts, upcoming deadlines |

Summary must separate confirmed facts from uncertain items and update as new
decisions are confirmed (PRD §9.5).

### 2.7 `reopen_decision`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `decision_id`, `workspace_id`, `requested_by` | Target + actor |
| Output | `decision_id`, `status` | Status becomes `reopened` |

Old decisions are **not** deleted; superseded decisions remain visible in history,
and the conflict detector respects the latest confirmed decision (PRD §9.7).

### 2.8 `log_conflict_action`
| Direction | Field | Notes |
| --- | --- | --- |
| Input | `conflict_id`, `action`, `actor_user_id` | `action` ∈ remind / reopen / ignore |
| Output | `conflict_id`, `status` | Resulting `conflict_status` |

Ignored conflicts are logged so repeated alerts for the same topic are suppressed
(PRD §9.4, §26.1).

---

## 3. LLM Prompt Contracts

The LLM layer returns **structured JSON** for these operations (PRD §20).

### 3.1 Decision Detection
**Input:** current message, thread context, recent messages.

```json
{
  "is_decision": true,
  "title": "Use PostgreSQL for v1",
  "summary": "The team agreed to use PostgreSQL for the first version.",
  "reason": "Structured project data fits PostgreSQL better.",
  "participants": ["Ayush", "Rahul", "Priya"],
  "confidence": 0.91,
  "needs_confirmation": true
}
```

### 3.2 Evidence Verification
**Input:** proposed answer, retrieved Slack evidence, confirmed memory.

```json
{
  "support_level": "SUPPORTED",
  "confidence": 0.88,
  "contradictions": [],
  "missing_evidence": [],
  "safe_to_answer": true
}
```

Support levels: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONFLICTING`,
`INSUFFICIENT_EVIDENCE`.

### 3.3 Conflict Detection
**Input:** new message, confirmed memory, latest Slack context.

```json
{
  "is_conflict": true,
  "conflict_type": "technology_choice",
  "severity": "medium",
  "explanation": "New message mentions MongoDB, but confirmed memory says PostgreSQL.",
  "recommended_action": "remind_decision"
}
```

---

## 4. LLM Behavior Guardrails (PRD §19)

The LLM must:

1. Return structured JSON for classification.
2. Separate confirmed facts from guesses.
3. Refuse to answer if evidence is insufficient.
4. Mention uncertainty clearly.
5. Avoid inventing unsupported decisions.
6. Use Slack evidence and memory as the primary context.
7. Prefer the latest confirmed memory over older raw messages.
8. Detect contradiction between new messages and confirmed memory.
9. Avoid exposing private evidence from unauthorized contexts.

These rules implement the **no-evidence refusal** behavior (PRD §9.6): when
support is `INSUFFICIENT_EVIDENCE`, AlignOS says it cannot confirm, distinguishes
"discussed" from "confirmed," and offers a next action (e.g. start a decision
thread) rather than hallucinating.

---

## 5. Risk: Don't Overbuild MCP (PRD §26.4)

- Keep Slack event handling in the FastAPI backend.
- Use MCP only for actual tools.
- Start with the 5 core tools; add `generate_project_summary`,
  `reopen_decision`, and `log_conflict_action` once the core loop works.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how the backend (MCP client) invokes
these tools, and [DATA_MODEL.md](DATA_MODEL.md) for the tables they read/write.
