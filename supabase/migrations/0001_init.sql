-- AlignOS initial schema (Supabase / PostgreSQL)
-- Mirrors Docs/DATA_MODEL.md. Forward-only migration.

create extension if not exists "pgcrypto";   -- gen_random_uuid()
create extension if not exists "pg_trgm";     -- trigram search on titles/summaries

-- ---------- Enums ----------
do $$ begin
  create type decision_status as enum ('proposed','confirmed','rejected','reopened','superseded');
exception when duplicate_object then null; end $$;

do $$ begin
  create type conflict_status as enum ('open','ignored','resolved','reopened_decision');
exception when duplicate_object then null; end $$;

do $$ begin
  create type memory_item_type as enum ('decision','task','blocker','deadline','question','summary');
exception when duplicate_object then null; end $$;

do $$ begin
  create type task_status as enum ('open','in_progress','done','cancelled');
exception when duplicate_object then null; end $$;

do $$ begin
  create type blocker_status as enum ('open','resolved');
exception when duplicate_object then null; end $$;

-- ---------- Core tenancy ----------
create table if not exists workspaces (
  id                   uuid primary key default gen_random_uuid(),
  slack_team_id        text unique not null,
  name                 text,
  installed_by_user_id text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create table if not exists channels (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspaces(id) on delete cascade,
  slack_channel_id text not null,
  name             text,
  is_monitored     boolean not null default true,
  is_private       boolean not null default false,
  created_at       timestamptz not null default now(),
  unique (workspace_id, slack_channel_id)
);

create table if not exists users (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  slack_user_id text not null,
  display_name  text,
  is_bot        boolean not null default false,
  created_at    timestamptz not null default now(),
  unique (workspace_id, slack_user_id)
);

-- ---------- Memory items (unified searchable surface) ----------
create table if not exists memory_items (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspaces(id) on delete cascade,
  channel_id   uuid references channels(id) on delete set null,
  type         memory_item_type not null,
  title        text not null,
  summary      text,
  status       text,
  confidence   numeric,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- ---------- Decisions ----------
create table if not exists decisions (
  id                     uuid primary key default gen_random_uuid(),
  workspace_id           uuid not null references workspaces(id) on delete cascade,
  channel_id             uuid references channels(id) on delete set null,
  thread_ts              text,
  title                  text not null,
  summary                text,
  reason                 text,
  status                 decision_status not null default 'proposed',
  confidence             numeric,
  confirmed_by_user_id   uuid references users(id) on delete set null,
  supersedes_decision_id uuid references decisions(id) on delete set null,
  evidence_count         integer not null default 0,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

-- ---------- Tasks ----------
create table if not exists tasks (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid not null references workspaces(id) on delete cascade,
  channel_id          uuid references channels(id) on delete set null,
  title               text not null,
  owner_user_id       uuid references users(id) on delete set null,
  status              task_status not null default 'open',
  due_date            date,
  evidence_message_ts text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- ---------- Blockers ----------
create table if not exists blockers (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid not null references workspaces(id) on delete cascade,
  channel_id          uuid references channels(id) on delete set null,
  title               text not null,
  description         text,
  status              blocker_status not null default 'open',
  evidence_message_ts text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- ---------- Conflicts ----------
create table if not exists conflicts (
  id                    uuid primary key default gen_random_uuid(),
  workspace_id          uuid not null references workspaces(id) on delete cascade,
  channel_id            uuid references channels(id) on delete set null,
  message_ts            text,
  conflict_type         text,
  severity              text,
  new_message_summary   text,
  conflicting_memory_id uuid references memory_items(id) on delete set null,
  explanation           text,
  status                conflict_status not null default 'open',
  created_at            timestamptz not null default now()
);

-- ---------- Evidence links ----------
create table if not exists evidence_links (
  id               uuid primary key default gen_random_uuid(),
  memory_item_id   uuid not null references memory_items(id) on delete cascade,
  source_type      text,
  slack_channel_id text,
  slack_message_ts text,
  slack_thread_ts  text,
  slack_user_id    text,
  snippet          text,
  created_at       timestamptz not null default now()
);

-- ---------- Audit events ----------
create table if not exists audit_events (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspaces(id) on delete cascade,
  channel_id    uuid references channels(id) on delete set null,
  actor_user_id uuid references users(id) on delete set null,
  event_type    text not null,
  target_id     uuid,
  metadata      jsonb,
  created_at    timestamptz not null default now()
);

-- ---------- Indexes ----------
create index if not exists idx_decisions_scope on decisions (workspace_id, channel_id, status);
create index if not exists idx_decisions_trgm on decisions using gin (title gin_trgm_ops, summary gin_trgm_ops);
create index if not exists idx_memory_scope on memory_items (workspace_id, channel_id, type, status);
create index if not exists idx_memory_trgm on memory_items using gin (title gin_trgm_ops, summary gin_trgm_ops);
create index if not exists idx_evidence_item on evidence_links (memory_item_id);
create index if not exists idx_conflicts_scope on conflicts (workspace_id, channel_id, status);
create index if not exists idx_audit_target on audit_events (target_id, event_type, created_at);
