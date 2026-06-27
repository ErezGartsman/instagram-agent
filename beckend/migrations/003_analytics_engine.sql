-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 003 — Phase 2A Analytics Engine
-- Apply in: Supabase Dashboard → SQL Editor (or psql)
--
-- Source of truth: the existing `interactions` table where kind='stage_change'
-- and payload JSONB = {from, to, reason, by, opportunity_id}.
-- No new event-capture tables needed — we mine what agents already write.
--
-- What this adds:
--   • sla_config          — operator-configurable SLA targets per stage.
--   • funnel_metrics      — materialized view: conversion rates + velocity
--                           between every stage pair. Refresh nightly via cron.
--   • lead_sla_status     — live view: per-lead hours in current stage vs
--                           target, colour-coded ok / warn / breach.
--
-- Safe to run multiple times: all DDL uses IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── sla_config ────────────────────────────────────────────────────────────────
-- One row per pipeline stage. target_hours = the operator's commitment to move a
-- lead forward within this window. warn_hours = the amber flag threshold.
-- Seeded with sensible defaults; update via the Supabase dashboard or a future
-- Settings UI.

CREATE TABLE IF NOT EXISTS sla_config (
    stage        TEXT PRIMARY KEY,
    target_hours INT  NOT NULL,   -- breach threshold — lead has been stuck too long
    warn_hours   INT  NOT NULL    -- warn threshold  — lead approaching breach
);

INSERT INTO sla_config (stage, target_hours, warn_hours) VALUES
    ('engaged',   24,  16),   -- first response within 24h
    ('qualified',  48,  36),  -- move to captured within 48h of qualifying
    ('captured',   72,  48),  -- brief within 72h of capturing context
    ('briefed',    48,  36),  -- present a booking slot within 48h
    ('booked',    168, 120)   -- session within 7 days of booking (practical)
ON CONFLICT (stage) DO NOTHING;


-- ── funnel_metrics ────────────────────────────────────────────────────────────
-- Materialized for query speed — the raw interactions table can be large.
-- Refreshed nightly by the APScheduler cron in scheduler.py.
--
-- Two complementary lenses:
--
--   conversion_pct  — of every lead that entered from_stage, what % moved to
--                     to_stage? Reveals drop-off between buckets.
--
--   avg / median hours_in_stage — how long did leads actually spend in
--                     from_stage before moving? Reveals velocity bottlenecks.
--
-- Velocity calculation: for each person, find paired stage_change events
-- (enter X then leave X) and compute seconds between them. Using a self-join
-- on interactions so we don't need a separate audit table.

CREATE MATERIALIZED VIEW IF NOT EXISTS funnel_metrics AS
WITH

-- How many unique leads have ever entered each stage (payload->>'to')
entries AS (
    SELECT
        payload->>'to'            AS stage,
        COUNT(DISTINCT person_id) AS entered_count
    FROM   interactions
    WHERE  kind = 'stage_change'
      AND  payload->>'to' IS NOT NULL
    GROUP  BY payload->>'to'
),

-- For each forward transition pair, count leads and compute velocity
transitions AS (
    SELECT
        t.payload->>'from'          AS from_stage,
        t.payload->>'to'            AS to_stage,
        COUNT(*)                    AS transition_count,
        COUNT(DISTINCT t.person_id) AS unique_leads,
        -- Time between entering from_stage and leaving it (via self-join on entry event)
        AVG(
            EXTRACT(EPOCH FROM (t.occurred_at - entry.occurred_at)) / 3600.0
        )::NUMERIC(8,1)             AS avg_hours_in_stage,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (t.occurred_at - entry.occurred_at)) / 3600.0
        )::NUMERIC(8,1)             AS median_hours_in_stage,
        MAX(t.occurred_at)          AS last_transition_at
    FROM interactions t
    -- Find the event that moved this person INTO from_stage
    LEFT JOIN LATERAL (
        SELECT occurred_at
        FROM   interactions
        WHERE  person_id = t.person_id
          AND  kind      = 'stage_change'
          AND  payload->>'to' = t.payload->>'from'
          AND  occurred_at < t.occurred_at
        ORDER  BY occurred_at DESC
        LIMIT  1
    ) entry ON TRUE
    WHERE  t.kind              = 'stage_change'
      AND  t.payload->>'from'  IS NOT NULL
      AND  t.payload->>'to'    IS NOT NULL
    GROUP  BY t.payload->>'from', t.payload->>'to'
)

SELECT
    tr.from_stage,
    tr.to_stage,
    tr.transition_count,
    tr.unique_leads,
    e.entered_count                                     AS total_entered_from_stage,
    ROUND(
        tr.unique_leads::NUMERIC / NULLIF(e.entered_count, 0) * 100,
        1
    )                                                   AS conversion_pct,
    tr.avg_hours_in_stage,
    tr.median_hours_in_stage,
    tr.last_transition_at
FROM  transitions tr
LEFT  JOIN entries e ON e.stage = tr.from_stage
ORDER BY tr.from_stage, tr.to_stage;

-- Index for the Analytics endpoint (filters by from_stage)
CREATE UNIQUE INDEX IF NOT EXISTS idx_funnel_metrics_pair
    ON funnel_metrics (from_stage, to_stage);


-- ── lead_sla_status ───────────────────────────────────────────────────────────
-- Live (non-materialized) view — always reflects the current moment.
-- Joins open opportunities against sla_config to produce a per-lead SLA verdict.
-- Used by:
--   • GET /api/cockpit/analytics/sla          — the SLA dashboard table
--   • The future Leads tab in AnalyticsPage   — colour-coded breach indicators

CREATE OR REPLACE VIEW lead_sla_status AS
SELECT
    o.id                                                AS opportunity_id,
    o.person_id,
    p.display_name                                      AS person_name,
    o.stage,
    o.stage_entered_at,
    -- Hours the lead has been in the current stage (NULL if stage_entered_at missing)
    ROUND(
        EXTRACT(EPOCH FROM (NOW() - o.stage_entered_at)) / 3600.0,
        1
    )::NUMERIC(8,1)                                     AS hours_in_stage,
    sc.target_hours,
    sc.warn_hours,
    CASE
        WHEN o.stage_entered_at IS NULL                                             THEN 'unknown'
        WHEN EXTRACT(EPOCH FROM (NOW() - o.stage_entered_at)) / 3600 > sc.target_hours THEN 'breach'
        WHEN EXTRACT(EPOCH FROM (NOW() - o.stage_entered_at)) / 3600 > sc.warn_hours   THEN 'warn'
        ELSE 'ok'
    END                                                 AS sla_status
FROM  opportunities o
JOIN  person        p  ON p.id    = o.person_id
LEFT  JOIN sla_config sc ON sc.stage = o.stage
WHERE o.closed_at    IS NULL
  AND (o.snoozed_until IS NULL OR o.snoozed_until <= NOW());


-- ── Initial funnel_metrics populate ──────────────────────────────────────────
-- Materialise once on apply. Future refreshes run nightly via APScheduler.
REFRESH MATERIALIZED VIEW funnel_metrics;


COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verification queries — run after applying to confirm everything landed:
--
--   SELECT * FROM sla_config ORDER BY target_hours;
--   -- Expected: 5 rows (engaged, qualified, captured, briefed, booked)
--
--   SELECT * FROM funnel_metrics;
--   -- Expected: rows for any stage_change interactions already in the DB.
--   -- Empty is fine on a fresh DB — rows appear as agents advance leads.
--
--   SELECT * FROM lead_sla_status ORDER BY hours_in_stage DESC NULLS LAST LIMIT 5;
--   -- Expected: one row per open opportunity with sla_status ok/warn/breach.
-- ─────────────────────────────────────────────────────────────────────────────
