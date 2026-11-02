-- Harden creator settings writes and make job budget reservations idempotent.
drop policy if exists creator_settings_insert_own on public.creator_settings;
drop policy if exists creator_settings_update_own on public.creator_settings;
revoke insert,update,delete on public.creator_settings from anon,authenticated;

drop index if exists public.provider_usage_job_kind_unique;
create unique index provider_usage_job_kind_unique on public.provider_usage(job_id,usage_kind);

-- OAuth credentials remain service-role only, as defined by the base migration.
revoke all on public.youtube_connections from anon,authenticated;