-- Atomic rolling-24-hour provider cost reservation for every user's production pipeline.
create or replace function public.reserve_creator_video_budget(
  p_user_id uuid,
  p_job_id uuid,
  p_estimated_cost numeric
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_cap numeric;
  v_spent numeric;
begin
  if p_estimated_cost is null or p_estimated_cost <= 0 then
    return false;
  end if;

  -- Serialize budget decisions for this user across concurrent worker replicas.
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

  select daily_budget_usd
    into v_cap
    from public.creator_settings
    where user_id = p_user_id
    for update;

  if v_cap is null or v_cap <= 0 then
    return false;
  end if;

  select coalesce(sum(cost_usd), 0)
    into v_spent
    from public.provider_usage
    where user_id = p_user_id
      and created_at >= now() - interval '24 hours'
      and not (job_id = p_job_id and usage_kind = 'estimated_reservation');

  if v_spent + p_estimated_cost > v_cap then
    return false;
  end if;

  insert into public.provider_usage(user_id, job_id, provider, usage_kind, cost_usd, usage)
  values (p_user_id, p_job_id, 'estimated-video-pipeline', 'estimated_reservation',
          p_estimated_cost, jsonb_build_object('reservation', true))
  on conflict (job_id, usage_kind)
  do update set cost_usd = excluded.cost_usd,
                usage = excluded.usage,
                created_at = now();

  return true;
end;
$$;

revoke all on function public.reserve_creator_video_budget(uuid,uuid,numeric) from public, anon, authenticated;
grant execute on function public.reserve_creator_video_budget(uuid,uuid,numeric) to service_role;
