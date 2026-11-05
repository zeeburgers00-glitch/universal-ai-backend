-- Core `uaib_*` tables for universal-ai-backend.
--
-- These were created by hand in the original project and had no migration, which meant a
-- fresh Supabase project could not actually run the finance ledger, and JARVIS memory had
-- nowhere durable to live. This file makes the whole set reproducible.
--
-- Rules, matching the existing tables in this project:
--   * RLS enabled with **zero** policies: only the service-role key can read or write.
--   * anon/authenticated are explicitly revoked, so a leaked anon key sees nothing.
--   * every statement is idempotent: safe to re-run.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Custom tools and execution logs (used by app/supabase_store.py)
-- ---------------------------------------------------------------------------
create table if not exists public.uaib_custom_tools (
  id text primary key,
  name text not null default '',
  category text not null default 'custom',
  protocol text not null default 'rest',
  description text not null default '',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.uaib_execution_logs (
  id bigserial primary key,
  tool_id text,
  action text,
  status text,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists uaib_execution_logs_created_idx
  on public.uaib_execution_logs (created_at desc);

-- ---------------------------------------------------------------------------
-- Runtime secrets (app/vault.py)
-- ---------------------------------------------------------------------------
create table if not exists public.uaib_runtime_secrets (
  name text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Finance ledger (app/finance_ledger.py)
-- ---------------------------------------------------------------------------
create table if not exists public.uaib_finance_entries (
  id uuid primary key default gen_random_uuid(),
  entry_type text not null check (entry_type in ('income', 'expense')),
  stream text not null default 'other',
  amount numeric(14, 2) not null check (amount > 0),
  currency text not null default 'USD' check (char_length(currency) = 3),
  verification text not null default 'estimate',
  reference text not null,
  note text not null default '',
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  recognized_as_realized_revenue boolean not null default false
);

create index if not exists uaib_finance_entries_created_idx
  on public.uaib_finance_entries (created_at desc);

create table if not exists public.uaib_payout_requests (
  id uuid primary key default gen_random_uuid(),
  provider text not null default 'other',
  amount numeric(14, 2) not null check (amount > 0),
  currency text not null default 'USD' check (char_length(currency) = 3),
  note text not null default '',
  status text not null default 'awaiting_approval',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  approved_at timestamptz,
  approval_note text
);

-- ---------------------------------------------------------------------------
-- JARVIS durable memory (app/jarvis.py + app/mind.py)
--
-- Local SQLite stays the source of truth for speed; these tables are the durable copy so a
-- new machine (or a wiped Kaggle session) can pull memory back.
-- ---------------------------------------------------------------------------
create table if not exists public.uaib_jarvis_facts (
  key text primary key,
  value text not null,
  source text not null default 'user',
  updated_at timestamptz not null default now()
);

create table if not exists public.uaib_jarvis_lessons (
  id uuid primary key default gen_random_uuid(),
  text text not null unique,
  source text not null default 'reflection',
  evidence text not null default '',
  created_at timestamptz not null default now()
);

create table if not exists public.uaib_jarvis_journal (
  id bigserial primary key,
  at timestamptz not null default now(),
  entry text not null,
  mood text not null default '',
  kind text not null default 'note'
);

create index if not exists uaib_jarvis_journal_at_idx
  on public.uaib_jarvis_journal (at desc);

-- ---------------------------------------------------------------------------
-- Lock everything down: RLS on, no policies (service role bypasses RLS)
-- ---------------------------------------------------------------------------
do $$
declare
  t text;
begin
  foreach t in array array[
    'uaib_custom_tools', 'uaib_execution_logs', 'uaib_runtime_secrets',
    'uaib_finance_entries', 'uaib_payout_requests',
    'uaib_jarvis_facts', 'uaib_jarvis_lessons', 'uaib_jarvis_journal'
  ]
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
