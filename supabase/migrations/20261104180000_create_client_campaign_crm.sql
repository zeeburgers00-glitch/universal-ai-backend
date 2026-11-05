-- Private CRM storage for the international direct-client content agency campaign.
-- All access is through the authenticated Universal AI Backend API using the server-only service role.
create table if not exists public.uaib_client_campaign_leads (
  id uuid primary key default gen_random_uuid(),
  campaign_id text not null,
  business_name text not null,
  website_url text not null,
  source_url text not null,
  contact_source_url text,
  industry text not null,
  city text not null default '',
  country text not null,
  public_contact text not null default '',
  contact_method text not null default 'none'
    check (contact_method in ('business_email', 'official_contact_form', 'public_phone', 'none')),
  qualification text not null default 'B' check (qualification in ('A', 'B', 'C')),
  lead_status text not null default 'research_needed'
    check (lead_status in ('research_needed', 'qualified', 'draft_ready', 'awaiting_approval',
                           'approved_to_send', 'contacted', 'replied', 'won', 'lost', 'do_not_contact')),
  fit_evidence text not null,
  content_angle text not null,
  verified_on date not null,
  notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (campaign_id, website_url)
);

create index if not exists uaib_client_campaign_leads_campaign_status_idx
  on public.uaib_client_campaign_leads (campaign_id, lead_status, qualification);
create index if not exists uaib_client_campaign_leads_updated_idx
  on public.uaib_client_campaign_leads (updated_at desc);

create table if not exists public.uaib_client_campaign_drafts (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.uaib_client_campaign_leads(id) on delete cascade,
  campaign_id text not null,
  draft_type text not null check (draft_type in ('first_touch', 'sample_brief', 'pilot_proposal', 'retainer_proposal')),
  recipient text not null default '',
  recipient_channel text not null default 'manual_only'
    check (recipient_channel in ('business_email', 'official_contact_form', 'manual_only')),
  subject text not null default '',
  body text not null,
  sample_concept jsonb not null default '{}'::jsonb,
  notes text not null default '',
  approval_status text not null default 'awaiting_approval'
    check (approval_status in ('awaiting_approval', 'approved_to_send', 'rejected')),
  approved_at timestamptz,
  approval_note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists uaib_client_campaign_drafts_campaign_status_idx
  on public.uaib_client_campaign_drafts (campaign_id, approval_status, created_at desc);
create index if not exists uaib_client_campaign_drafts_lead_idx
  on public.uaib_client_campaign_drafts (lead_id, created_at desc);

alter table public.uaib_client_campaign_leads enable row level security;
alter table public.uaib_client_campaign_drafts enable row level security;

-- Explicit server-only access. Never expose prospect or draft data through anonymous or authenticated client roles.
revoke all on table public.uaib_client_campaign_leads from public, anon, authenticated;
revoke all on table public.uaib_client_campaign_drafts from public, anon, authenticated;
grant select, insert, update, delete on table public.uaib_client_campaign_leads to service_role;
grant select, insert, update, delete on table public.uaib_client_campaign_drafts to service_role;
