# AlignOS Data Model

The verified memory layer lives in **Neon PostgreSQL** (serverless Postgres,
accessed via psycopg). This document
specifies all 10 tables, their columns, enums, scoping rules, and suggested
indexes.

> **Status legend:** Fields marked **(spec)** are enumerated directly in PRD §18.
> Fields marked **(proposed)** are reasonable additions for tables the PRD lists
> but does not fully specify (`workspaces`, `channels`, `users`, `blockers`,
> `audit_events`); ratify these during implementation.

> **Convention:** all `id` columns are `uuid` (default `gen_random_uuid()`);
> all `*_at` columns are `timestamptz`; Slack identifiers (`slack_*_id`,
> `*_ts`) are `text` because Slack message timestamps (`ts`) are string values.

---

## 1. Scoping & Tenancy

Every memory row is scoped by `workspace_id` and (where relevant) `channel_id`,
so a single deployment can serve multiple Slack workspaces and so answers never
leak across workspace/channel boundaries (PRD §9.3, §14.4).

- All queries from the agent filter by `workspace_id`.
- Channel-scoped reads additionally filter by `channel_id`.
- Consider Postgres Row Level Security (RLS) keyed on `workspace_id` if/when
  multi-tenant access is exposed beyond the trusted backend role.

---

## 2. Enums

| Enum | Values |
| --- | --- |
| `decision_status` | `proposed`, `confirmed`, `rejected`, `reopened`, `superseded` |
| `conflict_status` | `open`, `ignored`, `resolved`, `reopened_decision` |
| `memory_item_type` | `decision`, `task`, `blocker`, `deadline`, `question`, `summary` |
| `support_level` (verification output, not stored as a column by default) | `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONFLICTING`, `INSUFFICIENT_EVIDENCE` |
| `task_status` (proposed) | `open`, `in_progress`, `done`, `cancelled` |
| `blocker_status` (proposed) | `open`, `resolved` |

---

## 3. Tables

### 3.1 `workspaces` (proposed)
One row per Slack workspace where AlignOS is installed.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `slack_team_id` | text | Slack workspace/team ID, unique |
| `name` | text | Workspace display name |
| `bot_token` | text | Stored securely (prefer a secrets store / env over plaintext) |
| `installed_by_user_id` | text | Slack user who installed the app |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

### 3.2 `channels` (proposed)
Channels the bot monitors; supports channel-level opt-out (PRD §14.4).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `slack_channel_id` | text | Slack channel ID |
| `name` | text | Channel name |
| `is_monitored` | boolean | Opt-out flag (default `true`) |
| `is_private` | boolean | Affects evidence exposure rules |
| `created_at` | timestamptz | |

### 3.3 `users` (proposed)
Slack users referenced by decisions, tasks, and evidence.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `slack_user_id` | text | Slack user ID |
| `display_name` | text | |
| `is_bot` | boolean | Used to ignore bot messages (loop prevention) |
| `created_at` | timestamptz | |

### 3.4 `decisions` (spec)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `channel_id` | uuid | FK → `channels.id` |
| `thread_ts` | text | Slack thread timestamp |
| `title` | text | Short decision title |
| `summary` | text | What was decided |
| `reason` | text | Why it was decided |
| `status` | `decision_status` | See enums |
| `confidence` | numeric | 0–1 detection/verification confidence |
| `confirmed_by_user_id` | uuid | FK → `users.id`, nullable until confirmed |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |
| `supersedes_decision_id` | uuid | FK → `decisions.id`, nullable (decision chaining) |
| `evidence_count` | integer | Count of linked evidence rows |

### 3.5 `tasks` (spec)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `channel_id` | uuid | FK → `channels.id` |
| `title` | text | |
| `owner_user_id` | uuid | FK → `users.id`, nullable |
| `status` | `task_status` (proposed) | |
| `due_date` | date | nullable |
| `evidence_message_ts` | text | Source Slack message `ts` |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

### 3.6 `blockers` (proposed)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `channel_id` | uuid | FK → `channels.id` |
| `title` | text | |
| `description` | text | |
| `status` | `blocker_status` (proposed) | |
| `evidence_message_ts` | text | Source Slack message `ts` |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

### 3.7 `conflicts` (spec)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `channel_id` | uuid | FK → `channels.id` |
| `message_ts` | text | Slack `ts` of the conflicting message |
| `conflict_type` | text | e.g. `technology_choice` |
| `severity` | text | `low` / `medium` / `high` |
| `new_message_summary` | text | What the new message claimed |
| `conflicting_memory_id` | uuid | FK → `memory_items.id` (or `decisions.id`) |
| `explanation` | text | Why this is a conflict |
| `status` | `conflict_status` | See enums |
| `created_at` | timestamptz | |

### 3.8 `evidence_links` (spec)
Pointers to Slack messages that support a memory item — AlignOS stores
references, **not** full message history (PRD §14.3, §26.5).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `memory_item_id` | uuid | FK → `memory_items.id` |
| `source_type` | text | e.g. `slack_message`, `thread`, `file` |
| `slack_channel_id` | text | |
| `slack_message_ts` | text | |
| `slack_thread_ts` | text | nullable |
| `slack_user_id` | text | Author of the evidence message |
| `snippet` | text | Short quoted excerpt for display |
| `created_at` | timestamptz | |

### 3.9 `memory_items` (spec)
The generic memory record. Specialized tables (`decisions`, `tasks`, `blockers`,
`conflicts`) hold type-specific fields; `memory_items` provides a unified,
searchable surface and is the target of `evidence_links`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `channel_id` | uuid | FK → `channels.id` |
| `type` | `memory_item_type` | See enums |
| `title` | text | |
| `summary` | text | |
| `status` | text | Mirrors the relevant status enum for the type |
| `confidence` | numeric | 0–1 |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

### 3.10 `audit_events` (proposed)
Lightweight action log (confirmations, ignores, reopenings) — supports
`log_conflict_action` and suppressing repeated alerts (PRD §9.4, §26.1).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | PK |
| `workspace_id` | uuid | FK → `workspaces.id` |
| `channel_id` | uuid | FK → `channels.id`, nullable |
| `actor_user_id` | uuid | FK → `users.id`, nullable |
| `event_type` | text | e.g. `decision_confirmed`, `conflict_ignored`, `decision_reopened` |
| `target_id` | uuid | ID of the affected decision/conflict/memory item |
| `metadata` | jsonb | Free-form context |
| `created_at` | timestamptz | |

---

## 4. Relationships (summary)

```text
workspaces 1───* channels 1───* (decisions, tasks, blockers, conflicts, memory_items)
workspaces 1───* users
memory_items 1───* evidence_links
decisions   *───1 decisions          (supersedes_decision_id, self-reference)
conflicts   *───1 memory_items        (conflicting_memory_id)
audit_events *──1 workspaces/users    (action history)
```

---

## 5. Suggested Indexes

- `decisions (workspace_id, channel_id, status)` — fast scoped lookups of active
  decisions.
- `decisions (workspace_id, title)` / full-text or `pg_trgm` on `title`+`summary`
  — topic search for `search_memory` and conflict checks.
- `memory_items (workspace_id, channel_id, type, status)` — summary generation.
- `evidence_links (memory_item_id)` — fetch evidence for a memory item.
- `conflicts (workspace_id, channel_id, status)` — open-conflict queries and
  repeat-alert suppression.
- `audit_events (target_id, event_type, created_at)` — recent action history.

---

## 6. Migrations

DDL is **not** part of this documentation pass. When implementation begins,
create migrations under `migrations/` and apply them to Neon with
`psql "$DATABASE_URL" -f migrations/0001_init.sql`. Keep migrations forward-only
and checked into git so the schema is reproducible. The initial schema is in
[../migrations/0001_init.sql](../migrations/0001_init.sql).
