-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 005 — close the anon/authenticated exposure of the analytics view
-- and materialized view (security audit, 2026-07-08).
--
-- FINDING (proven live): the public `anon` role — the key shipped in the browser
-- bundle — could read lead PII via the Data API:
--     GET /rest/v1/lead_sla_status?select=*      → 24 rows (lead names + SLA state)
--     GET /rest/v1/funnel_metrics?select=*       →  6 rows (funnel analytics)
-- `lead_sla_status` is a SECURITY DEFINER view (runs as its postgres creator, so
-- it BYPASSES the deny-all RLS on person/opportunities/sla_config), and both
-- objects carried the permissive default GRANT ALL to anon + authenticated.
--
-- FIX:
--   1. Flip the view to security_invoker so it runs with the CALLER's RLS. An
--      anon/authenticated caller then hits deny-all RLS and sees zero rows even
--      if SELECT is ever re-granted (defense in depth).
--   2. Revoke all privileges on both objects from the browser-facing roles.
--
-- SAFE: the backend reads both objects as the `postgres` owner (BYPASSRLS), which
-- keeps its explicit privileges; `service_role` is intentionally left untouched.
-- The frontend never queries these objects directly — cockpit analytics/SLA data
-- is served through the FastAPI backend.
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. View → run under the querying role's RLS instead of the definer's.
ALTER VIEW public.lead_sla_status SET (security_invoker = on);

-- 2. Remove the view + matview from the anon/authenticated API surface.
REVOKE ALL ON public.lead_sla_status FROM anon, authenticated;
REVOKE ALL ON public.funnel_metrics  FROM anon, authenticated;
