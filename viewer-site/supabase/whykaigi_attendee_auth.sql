-- WhyKaigi attendee identity registry and 30-day room-access audit.
-- Authentication remains in Supabase Auth; live room payloads remain in Sites D1.

create table if not exists public.whykaigi_attendee_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null check (char_length(email) between 3 and 254),
  display_name text not null default '' check (char_length(display_name) <= 120),
  avatar_url text not null default '' check (char_length(avatar_url) <= 500),
  provider text not null check (provider = 'google'),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table if not exists public.whykaigi_room_access_logs (
  event_id uuid primary key default gen_random_uuid(),
  room_id text not null check (char_length(room_id) between 20 and 64),
  user_id uuid not null references auth.users(id) on delete cascade,
  email text not null check (char_length(email) between 3 and 254),
  display_name text not null default '' check (char_length(display_name) <= 120),
  provider text not null check (provider = 'google'),
  event_type text not null check (event_type in ('access_granted')),
  occurred_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days')
);

create index if not exists whykaigi_room_access_logs_room_time_idx
  on public.whykaigi_room_access_logs (room_id, occurred_at desc);
create index if not exists whykaigi_room_access_logs_user_time_idx
  on public.whykaigi_room_access_logs (user_id, occurred_at desc);
create index if not exists whykaigi_room_access_logs_expiry_idx
  on public.whykaigi_room_access_logs (expires_at);

alter table public.whykaigi_attendee_profiles enable row level security;
alter table public.whykaigi_room_access_logs enable row level security;

revoke all on table public.whykaigi_attendee_profiles from anon;
revoke all on table public.whykaigi_room_access_logs from anon;
revoke all on table public.whykaigi_attendee_profiles from authenticated;
revoke all on table public.whykaigi_room_access_logs from authenticated;
grant select, insert, update on table public.whykaigi_attendee_profiles to authenticated;
grant select, insert on table public.whykaigi_room_access_logs to authenticated;

create policy "whykaigi_profiles_select_own"
  on public.whykaigi_attendee_profiles
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "whykaigi_profiles_insert_own_verified_email"
  on public.whykaigi_attendee_profiles
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and lower(email) = lower((select auth.jwt()) ->> 'email')
    and (
      provider = coalesce((select auth.jwt()) -> 'app_metadata' ->> 'provider', '')
      or coalesce((select auth.jwt()) -> 'app_metadata' -> 'providers', '[]'::jsonb) ? provider
    )
  );

create policy "whykaigi_profiles_update_own_verified_email"
  on public.whykaigi_attendee_profiles
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and lower(email) = lower((select auth.jwt()) ->> 'email')
    and (
      provider = coalesce((select auth.jwt()) -> 'app_metadata' ->> 'provider', '')
      or coalesce((select auth.jwt()) -> 'app_metadata' -> 'providers', '[]'::jsonb) ? provider
    )
  );

create policy "whykaigi_access_logs_select_own"
  on public.whykaigi_room_access_logs
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create policy "whykaigi_access_logs_insert_own_verified_email"
  on public.whykaigi_room_access_logs
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and lower(email) = lower((select auth.jwt()) ->> 'email')
    and (
      provider = coalesce((select auth.jwt()) -> 'app_metadata' ->> 'provider', '')
      or coalesce((select auth.jwt()) -> 'app_metadata' -> 'providers', '[]'::jsonb) ? provider
    )
  );

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create or replace function private.prune_whykaigi_access_logs()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.whykaigi_room_access_logs where expires_at <= now();
  return new;
end;
$$;

revoke all on function private.prune_whykaigi_access_logs() from public, anon, authenticated;

drop trigger if exists whykaigi_access_logs_prune_after_insert
  on public.whykaigi_room_access_logs;
create trigger whykaigi_access_logs_prune_after_insert
  after insert on public.whykaigi_room_access_logs
  for each statement execute function private.prune_whykaigi_access_logs();

comment on table public.whykaigi_attendee_profiles is
  'Verified WhyKaigi attendee identities managed by Supabase Auth.';
comment on table public.whykaigi_room_access_logs is
  'WhyKaigi room entry audit; rows expire after 30 days.';
