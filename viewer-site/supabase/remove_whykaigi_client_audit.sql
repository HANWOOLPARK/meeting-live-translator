-- Remove the retired WhyKaigi PostgREST identity and room-audit store.
--
-- Supabase Auth remains the identity provider. The relay validates the signed-in
-- user with /auth/v1/user and keeps the room-scoped access audit in D1 only.
-- These statements intentionally touch only WhyKaigi-owned objects; the shared
-- project's generic `private` schema and unrelated BJT objects are left intact.

drop table if exists public.whykaigi_room_access_logs;
drop table if exists public.whykaigi_attendee_profiles;
drop function if exists private.prune_whykaigi_access_logs();
