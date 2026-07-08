-- P0 security lockdown (see PLAN.md).
--
-- Enables RLS on both tables with NO policies: the PostgREST API (anon key)
-- can no longer read or write anything. Nothing uses the anon key yet, and
-- the sync scripts connect over direct Postgres, which bypasses RLS — so
-- this changes nothing about current workflows, it just closes the door.
--
-- P1 (multi-user) adds real policies: per-user CRUD on collection,
-- read-only cards, pod-scoped sharing.

alter table cards enable row level security;
alter table collection enable row level security;

-- Make the view run with the querying user's permissions instead of the
-- view creator's (fixes the security_definer_view advisor error).
alter view collection_enriched set (security_invoker = true);
