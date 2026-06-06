-- Upgrade an existing pre-text database: convert Slack scoping/user columns from
-- uuid to text so they can hold Slack string IDs (e.g. "T0B8PUWB1FE").
-- Non-destructive (no row deletion). Fresh installs get this directly from
-- 0001_init.sql and can skip this file.

-- decisions
alter table decisions drop constraint if exists decisions_workspace_id_fkey;
alter table decisions drop constraint if exists decisions_channel_id_fkey;
alter table decisions drop constraint if exists decisions_confirmed_by_user_id_fkey;
alter table decisions alter column workspace_id type text using workspace_id::text;
alter table decisions alter column channel_id type text using channel_id::text;
alter table decisions alter column confirmed_by_user_id type text using confirmed_by_user_id::text;

-- memory_items
alter table memory_items drop constraint if exists memory_items_workspace_id_fkey;
alter table memory_items drop constraint if exists memory_items_channel_id_fkey;
alter table memory_items alter column workspace_id type text using workspace_id::text;
alter table memory_items alter column channel_id type text using channel_id::text;

-- tasks
alter table tasks drop constraint if exists tasks_workspace_id_fkey;
alter table tasks drop constraint if exists tasks_channel_id_fkey;
alter table tasks drop constraint if exists tasks_owner_user_id_fkey;
alter table tasks alter column workspace_id type text using workspace_id::text;
alter table tasks alter column channel_id type text using channel_id::text;
alter table tasks alter column owner_user_id type text using owner_user_id::text;

-- blockers
alter table blockers drop constraint if exists blockers_workspace_id_fkey;
alter table blockers drop constraint if exists blockers_channel_id_fkey;
alter table blockers alter column workspace_id type text using workspace_id::text;
alter table blockers alter column channel_id type text using channel_id::text;

-- conflicts
alter table conflicts drop constraint if exists conflicts_workspace_id_fkey;
alter table conflicts drop constraint if exists conflicts_channel_id_fkey;
alter table conflicts alter column workspace_id type text using workspace_id::text;
alter table conflicts alter column channel_id type text using channel_id::text;

-- audit_events
alter table audit_events drop constraint if exists audit_events_workspace_id_fkey;
alter table audit_events drop constraint if exists audit_events_channel_id_fkey;
alter table audit_events drop constraint if exists audit_events_actor_user_id_fkey;
alter table audit_events alter column workspace_id type text using workspace_id::text;
alter table audit_events alter column channel_id type text using channel_id::text;
alter table audit_events alter column actor_user_id type text using actor_user_id::text;
