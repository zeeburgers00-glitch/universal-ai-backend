-- AI YouTube Studio Autopilot: user-owned settings, encrypted OAuth tokens and durable production history.
create extension if not exists pgcrypto;

create table if not exists public.creator_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  niche text not null default 'Educational explainers',
  language text not null default 'English',
  target_audience text not null default 'Curious adults',
  schedule_time text not null default '18:00' check (schedule_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
  timezone text not null default 'Asia/Karachi',
  daily_budget_usd numeric(12,2) not null default 0 check (daily_budget_usd >= 0),
  autopublish_enabled boolean not null default false,
  made_for_kids boolean null,
  contains_synthetic_media boolean null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.youtube_connections (
  user_id uuid primary key references auth.users(id) on delete cascade,
  channel_id text not null,
  channel_title text not null,
  channel_thumbnail text,
  access_token_enc text,
  refresh_token_enc text not null,
  expires_at timestamptz,
  scopes text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.production_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  topic text not null check (length(topic) between 8 and 300),
  idempotency_key text not null,
  status text not null default 'queued' check (status in ('queued','running','blocked','draft_ready','scheduled','failed','cancelled')),
  stage text not null default 'queued',
  progress integer not null default 0 check (progress between 0 and 100),
  error text,
  output jsonb not null default '{}'::jsonb,
  estimated_cost_usd numeric(12,4) not null default 0 check (estimated_cost_usd >= 0),
  youtube_video_id text,
  upload_started_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  unique(user_id,idempotency_key)
);
create index if not exists production_jobs_user_created_idx on public.production_jobs(user_id,created_at desc);
create index if not exists production_jobs_status_idx on public.production_jobs(status);

create table if not exists public.provider_usage (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid references public.production_jobs(id) on delete set null,
  provider text not null,
  usage_kind text not null,
  cost_usd numeric(12,4) not null default 0 check (cost_usd >= 0),
  usage jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists provider_usage_user_created_idx on public.provider_usage(user_id,created_at desc);
create unique index if not exists provider_usage_job_kind_unique on public.provider_usage(job_id,usage_kind) where job_id is not null;

create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid references public.production_jobs(id) on delete cascade,
  event_type text not null,
  stage text,
  status text not null,
  message text not null check (length(message) <= 2000),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists audit_events_user_created_idx on public.audit_events(user_id,created_at desc);
create index if not exists audit_events_job_idx on public.audit_events(job_id,created_at asc);

alter table public.creator_settings enable row level security;
alter table public.youtube_connections enable row level security;
alter table public.production_jobs enable row level security;
alter table public.provider_usage enable row level security;
alter table public.audit_events enable row level security;

-- Users may inspect/update only their own non-secret settings.
drop policy if exists creator_settings_select_own on public.creator_settings;
create policy creator_settings_select_own on public.creator_settings for select to authenticated using (auth.uid()=user_id);
drop policy if exists creator_settings_insert_own on public.creator_settings;
create policy creator_settings_insert_own on public.creator_settings for insert to authenticated with check (auth.uid()=user_id);
drop policy if exists creator_settings_update_own on public.creator_settings;
create policy creator_settings_update_own on public.creator_settings for update to authenticated using (auth.uid()=user_id) with check (auth.uid()=user_id);

-- Browser users can read their jobs, costs and audit log, but only the server service role can write them.
drop policy if exists production_jobs_select_own on public.production_jobs;
create policy production_jobs_select_own on public.production_jobs for select to authenticated using (auth.uid()=user_id);
drop policy if exists provider_usage_select_own on public.provider_usage;
create policy provider_usage_select_own on public.provider_usage for select to authenticated using (auth.uid()=user_id);
drop policy if exists audit_events_select_own on public.audit_events;
create policy audit_events_select_own on public.audit_events for select to authenticated using (auth.uid()=user_id);

-- OAuth tokens are private to the server. Do not grant any direct client access.
revoke all on public.youtube_connections from anon,authenticated;
revoke insert,update,delete on public.production_jobs from anon,authenticated;
revoke insert,update,delete on public.provider_usage from anon,authenticated;
revoke insert,update,delete on public.audit_events from anon,authenticated;

-- Private media bucket; the worker uses the Supabase service role and returns short-lived signed URLs.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('youtube-media','youtube-media',false,2147483648,array['video/mp4','audio/mpeg','text/vtt','application/x-subrip','image/jpeg','image/png'])
on conflict (id) do nothing;
