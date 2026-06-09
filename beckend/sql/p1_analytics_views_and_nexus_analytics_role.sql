-- ─────────────────────────────────────────────────────────────────────────────
-- P1 — Secure, PII-stripped lead BI layer for Power BI (DirectQuery)
--
-- Creates aggregate-only views over bot_events + leads in a dedicated `analytics`
-- schema (NOT exposed to the PostgREST API), plus a dedicated least-privilege
-- read-only role `nexus_analytics` that can SELECT the views and NOTHING else.
--
-- SECURITY MODEL (verified live):
--   • Views are owned by `postgres` (BYPASSRLS) → they read the underlying tables
--     via owner-rights (security_invoker = false, the default), so they return
--     data despite the deny-all RLS on the base tables.
--   • nexus_analytics has SELECT on the two views only — has_table_privilege
--     confirms it CANNOT read public.leads / bot_events / messages (no raw PII).
--   • Views select ZERO PII: no phone, name, intent_summary, or chat_id/IGSID —
--     only dates, channel, and aggregate counts.
--
-- STATUS: applied + verified on the live Nexus project. This file is the record.
--
-- AFTER APPLYING — enable Power BI access (run with YOUR strong password):
--   ALTER ROLE nexus_analytics LOGIN PASSWORD '<openssl rand -base64 24>';
-- Then connect Power BI (PostgreSQL connector) with user = nexus_analytics; it
-- will see only analytics.funnel_daily and analytics.leads_summary.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS analytics;

-- Daily conversion funnel from bot_events (no PII — counts only).
CREATE OR REPLACE VIEW analytics.funnel_daily AS
SELECT
    (ts AT TIME ZONE 'UTC')::date                       AS day,
    channel,
    count(*) FILTER (WHERE event = 'icebreaker_hit')    AS icebreaker_hits,
    count(*) FILTER (WHERE event = 'lead_captured')     AS lead_captures,
    count(*) FILTER (WHERE event = 'context_provided')  AS context_provided,
    round(
        count(*) FILTER (WHERE event = 'lead_captured')::numeric
        / NULLIF(count(*) FILTER (WHERE event = 'icebreaker_hit'), 0), 4
    )                                                   AS conversion_rate
FROM public.bot_events
GROUP BY 1, 2;

-- Daily lead volume + CRM/alert health from leads (no PII).
CREATE OR REPLACE VIEW analytics.leads_summary AS
SELECT
    (created_at AT TIME ZONE 'UTC')::date               AS day,
    channel,
    count(*)                                            AS leads_total,
    count(*) FILTER (WHERE crm_synced_at IS NOT NULL)   AS leads_crm_synced,
    count(*) FILTER (WHERE notified_at   IS NOT NULL)   AS leads_notified
FROM public.leads
GROUP BY 1, 2;

-- Dedicated least-privilege BI role. NOLOGIN here (no secret committed);
-- enable login + password separately (see header).
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nexus_analytics') THEN
        CREATE ROLE nexus_analytics NOLOGIN;
    END IF;
END $$;

GRANT CONNECT ON DATABASE postgres TO nexus_analytics;
GRANT USAGE  ON SCHEMA analytics   TO nexus_analytics;
GRANT SELECT ON analytics.funnel_daily  TO nexus_analytics;
GRANT SELECT ON analytics.leads_summary TO nexus_analytics;

-- Verification (should return exactly the two analytics views):
-- SELECT grantee, table_name, privilege_type
-- FROM information_schema.role_table_grants
-- WHERE grantee = 'nexus_analytics' ORDER BY table_name;
