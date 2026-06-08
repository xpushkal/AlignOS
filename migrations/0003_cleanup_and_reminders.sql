-- Migration 0003: Cleanup Status and Reminders
-- Enables archiving memory items and scheduling user direct-message reminders.
-- Apply with: psql "$DATABASE_URL" -f migrations/0003_cleanup_and_reminders.sql

-- 1. Alter enums to support 'archived' status (autocommit mode is required)
alter type decision_status add value if not exists 'archived';
alter type task_status add value if not exists 'archived';
alter type blocker_status add value if not exists 'archived';

-- 2. Create reminders table
create table if not exists reminders (
  id             uuid primary key default gen_random_uuid(),
  workspace_id   text not null,
  task_id        uuid,
  owner_slack_id text not null,
  task_title     text not null,
  deadline       date,
  remind_at      timestamptz not null,
  status         text not null default 'scheduled', -- scheduled, sent, dismissed, completed
  created_at     timestamptz not null default now()
);

-- Index for background worker queries
create index if not exists idx_reminders_status on reminders (status, remind_at);
