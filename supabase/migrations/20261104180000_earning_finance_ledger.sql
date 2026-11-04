-- Private finance ledger for verified income, costs, and human-reviewed payout requests.
-- The backend service role is the only intended reader/writer. Never store wallet passwords,
-- API secrets, full bank account numbers, card data, or payment-provider access tokens here.

create table if not exists public.uaib_finance_entries (
  id uuid primary key default gen_random_uuid(),
  entry_type text not null check (entry_type in ('income','expense')),
  stream text not null,
  amount numeric(18,2) not null check (amount > 0),
  currency char(3) not null default 'USD',
  verification text not null default 'estimate'
    check (verification in ('estimate','invoice','provider_statement','verified_payment','receipt')),
  reference text not null,
  note text not null default '',
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  recognized_as_realized_revenue boolean not null default false
);

create index if not exists uaib_finance_entries_occurred_idx
  on public.uaib_finance_entries (occurred_at desc);
create index if not exists uaib_finance_entries_stream_idx
  on public.uaib_finance_entries (stream, entry_type);

create table if not exists public.uaib_payout_requests (
  id uuid primary key default gen_random_uuid(),
  provider text not null check (provider in ('paypal','payoneer','bank_transfer','other')),
  amount numeric(18,2) not null check (amount > 0),
  currency char(3) not null default 'USD',
  note text not null default '',
  status text not null default 'awaiting_approval'
    check (status in ('awaiting_approval','approved_for_manual_processing','rejected','paid')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  approved_at timestamptz,
  approval_note text
);

create index if not exists uaib_payout_requests_status_idx
  on public.uaib_payout_requests (status, created_at desc);

alter table public.uaib_finance_entries enable row level security;
alter table public.uaib_payout_requests enable row level security;
revoke all on public.uaib_finance_entries from anon, authenticated;
revoke all on public.uaib_payout_requests from anon, authenticated;
grant all on public.uaib_finance_entries to service_role;
grant all on public.uaib_payout_requests to service_role;
