# Earning Empire: operational rollout

## What exists today
The API exposes 120 on-demand earning-agent blueprints in 12 departments, workflow templates, a worker dispatch boundary, a content-agency lead/draft CRM, and a revenue-report adapter. A blueprint is not a running process or a source of income. The agent worker must be deployed and configured before tasks can execute.

## First revenue lane: productized content services
Start with one narrowly scoped offer (for example, 12 short-form video scripts/captions plus a monthly content calendar). Use public business information to qualify prospects, create a tailored sample, and save a personalized first-touch draft. Keep contact details to business-published channels, respect opt-outs and applicable marketing rules, and require a person to send outreach. Deliver a paid pilot before expanding to retainers.

## Required backend services
- FastAPI control plane: Railway Docker deployment.
- Supabase Postgres: apply all repository migrations, including `supabase/migrations/20261104180000_earning_finance_ledger.sql`.
- Redis + Celery/agent worker: use `workers/docker-compose.yml` as a reference; configure the worker's own secure production service.
- Model provider: configure one server-side provider key and provider-side spend limits.
- Worker authentication: distinct random API keys for agent, media, finance, and plugin workers; HTTPS only.

## New finance endpoints
- `GET /v1/finance/summary` — income, expenses, and verified income by currency.
- `GET /v1/finance/entries` — ledger history.
- `POST /v1/finance/entries` — record an income or expense with evidence classification.
- `GET /v1/finance/payout-requests` — review payout records.
- `POST /v1/finance/payout-requests` — create a manual payout request.
- `POST /v1/finance/payout-requests/{id}/approve` — record explicit approval for manual processing.

The finance ledger deliberately does not connect to PayPal, Payoneer, or a bank, and never stores payment credentials or destination account details. Approval does not initiate a transfer. Use the provider's official account interface to withdraw to a bank account you control.

## Budget and approval policy
Treat USD 100/month as a hard operational target: set actual provider spending caps and alerts, keep worker concurrency low (1–3 until measured), and pause nonessential jobs when the remaining budget is low. This API's budget metadata is not a billing cap. Drafting, research, and analysis can run unattended; external outreach, publishing, purchases, subscriptions, account changes, and money movement require separate explicit approval.

## Launch checklist
1. Apply Supabase migrations and confirm private RLS policies.
2. Set backend secrets in Railway's variable manager; never commit `.env` or credentials.
3. Deploy the API and verify `/health`, `/v1/earning/fleet`, and `/v1/runtime/capabilities`.
4. Deploy Redis/Celery/agent worker and set `AGENT_WORKER_URL` and `AGENT_WORKER_API_KEY`.
5. Set provider-side usage caps before sending any agent work.
6. Run a dry-run plan, then one low-cost task; inspect logs and ledger before increasing concurrency.
7. Deploy campaign CRM migrations before importing prospects. Keep outbound sending disabled until a separately reviewed, compliant sending workflow is explicitly enabled.
