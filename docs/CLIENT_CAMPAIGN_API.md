# Content agency client campaign API

Base route: `/v1/campaigns/content-agency`. All routes require the backend's `X-API-Key` header. Configure `BACKEND_API_KEY`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` on the server only.

## Routes

- `GET /status` — campaign policy and storage readiness.
- `POST /leads/import` — upsert up to 50 public business leads; duplicate campaign/website pairs merge.
- `GET /leads` — list leads, filter by qualification or lead status.
- `GET /leads/{lead_id}` — retrieve a lead.
- `POST /leads/{lead_id}/drafts` — save a personalized first-touch draft, sample brief, pilot proposal, or retainer proposal.
- `GET /drafts` — list proposal/outreach drafts and approval state.
- `POST /drafts/{draft_id}/approve` — record owner approval for the exact draft; **does not send it**.
- `POST /drafts/{draft_id}/reject` — reject a draft.

## Non-negotiable side-effect boundary

This API intentionally has no SMTP, email, DM, social publishing, or contact-form submission route. An `approved_to_send` draft is an approval record only. It must still be sent manually or through a separately reviewed integration after a separate explicit authorization. Do not mark a prospect contacted unless a human actually sends a message and records the outcome.

Lead imports must carry public HTTPS sources and contact-source links. Use business-role contact information only. Keep opt-outs as `do_not_contact`. Do not infer budgets, personal details, client interest, or purchase intent from public business listings.

## Database

Apply `supabase/migrations/20261104180000_create_client_campaign_crm.sql`. Both tables use RLS with no end-user policies and explicit grants only to `service_role`. Never expose the service-role key to a browser.
