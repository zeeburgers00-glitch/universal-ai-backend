-- Avoid row-by-row auth.uid() evaluation in the YouTube Studio RLS read policies.
drop policy if exists creator_settings_select_own on public.creator_settings;
create policy creator_settings_select_own
  on public.creator_settings for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists production_jobs_select_own on public.production_jobs;
create policy production_jobs_select_own
  on public.production_jobs for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists provider_usage_select_own on public.provider_usage;
create policy provider_usage_select_own
  on public.provider_usage for select to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists audit_events_select_own on public.audit_events;
create policy audit_events_select_own
  on public.audit_events for select to authenticated
  using ((select auth.uid()) = user_id);
