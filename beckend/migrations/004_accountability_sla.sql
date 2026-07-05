-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 004 — Close the Action Loop: accountability-based SLA
-- Apply in: Supabase Dashboard → SQL Editor (or via the Supabase MCP).
--
-- THE TRUTH FIX
-- Migration 003's lead_sla_status measured `hours_in_stage = now - stage_entered_at`
-- — i.e. how long a card has sat in a column. That is NOT neglect: the clock keeps
-- climbing even while the operator actively works the lead. Hence "575h breach" and
-- "20/22 breached" were false.
--
-- This migration reframes the SLA around ACCOUNTABILITY — "how long has this lead
-- been waiting on US." It resets when the operator reaches out, and restarts when
-- the lead replies and we haven't responded.
--
-- Operator touch  = interactions(kind IN 'outreach_click','contacted')  ∪  outbound_messages
-- Lead inbound     = messages (role='user') via sessions (channel='whatsapp')
-- Stage age        = opportunities.stage_entered_at  (fallback for untouched leads)
--
-- accountable_since = CASE
--   they replied after our last touch  → last_inbound_at      (ball in OUR court)
--   we reached out, no reply since      → last_operator_touch  (waiting on them — still
--                                          breaches per the "no limbo" rule)
--   never touched                       → stage_entered_at     (new-lead clock)
--
-- DECISIONS (ratified 2026-06-30):
--   1. Inbound re-opens the clock (ball back in our court).      → YES
--   2. Operator outreach fully resets the clock to green.        → FULL RESET
--   3. v1 scope: only the WhatsApp draft card logs outreach.     → card only
--   4. "Waiting on them" tail still breaches (no limbo).         → BREACHES
--
-- SAFE: CREATE OR REPLACE VIEW — preserves the original 9 columns in order and only
-- APPENDS 5 new ones, so every existing consumer keeps working. No data is mutated;
-- interactions are append-only. Rollback = re-run migration 003's view definition.
-- Indexes already exist (interactions_person_ts_idx, interactions_kind_ts_idx,
-- interactions_dedup_uniq) — no new indexes required.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

CREATE OR REPLACE VIEW lead_sla_status AS
SELECT
    -- ── original columns (order + types preserved for CREATE OR REPLACE) ──────
    o.id                                                AS opportunity_id,
    o.person_id,
    p.display_name                                      AS person_name,
    o.stage,
    o.stage_entered_at,
    round(EXTRACT(epoch FROM now() - o.stage_entered_at) / 3600.0, 1)::numeric(8,1)
                                                        AS hours_in_stage,
    sc.target_hours,
    sc.warn_hours,
    -- sla_status now keys off the ACCOUNTABILITY clock, not stage age.
    CASE
        WHEN acc.accountable_since IS NULL                                                  THEN 'unknown'::text
        WHEN EXTRACT(epoch FROM now() - acc.accountable_since) / 3600.0 > sc.target_hours   THEN 'breach'::text
        WHEN EXTRACT(epoch FROM now() - acc.accountable_since) / 3600.0 > sc.warn_hours     THEN 'warn'::text
        ELSE 'ok'::text
    END                                                 AS sla_status,
    -- ── new accountability columns (appended) ─────────────────────────────────
    touch.last_operator_touch_at,
    inb.last_inbound_at,
    acc.accountable_since,
    round(EXTRACT(epoch FROM now() - acc.accountable_since) / 3600.0, 1)::numeric(8,1)
                                                        AS hours_since_touch,
    acc.waiting_on
FROM opportunities o
JOIN person p ON p.id = o.person_id
LEFT JOIN sla_config sc ON sc.stage = o.stage
-- Most recent operator touch: cockpit wa.me click / confirmed send / API send.
LEFT JOIN LATERAL (
    SELECT GREATEST(
        (SELECT max(i.occurred_at) FROM interactions i
          WHERE i.person_id = o.person_id
            AND i.kind IN ('outreach_click', 'contacted')),
        (SELECT max(om.sent_at) FROM outbound_messages om
          WHERE om.person_id = o.person_id AND om.channel = 'whatsapp')
    ) AS last_operator_touch_at
) touch ON TRUE
-- Most recent inbound from the lead.
LEFT JOIN LATERAL (
    SELECT max(m.created_at) AS last_inbound_at
    FROM messages m
    JOIN sessions s ON s.id = m.session_id
    WHERE s.person_id = o.person_id
      AND s.channel = 'whatsapp'
      AND m.role = 'user'
) inb ON TRUE
-- Resolve the accountability anchor + who owes the next move.
LEFT JOIN LATERAL (
    SELECT
        CASE
            WHEN inb.last_inbound_at IS NOT NULL
                 AND (touch.last_operator_touch_at IS NULL
                      OR inb.last_inbound_at > touch.last_operator_touch_at)
                THEN inb.last_inbound_at
            WHEN touch.last_operator_touch_at IS NOT NULL
                THEN touch.last_operator_touch_at
            ELSE o.stage_entered_at
        END AS accountable_since,
        CASE
            WHEN inb.last_inbound_at IS NOT NULL
                 AND (touch.last_operator_touch_at IS NULL
                      OR inb.last_inbound_at > touch.last_operator_touch_at)
                THEN 'operator'::text   -- lead replied; we owe the next move
            WHEN touch.last_operator_touch_at IS NOT NULL
                THEN 'lead'::text       -- we reached out; awaiting their reply
            ELSE 'untouched'::text      -- never engaged
        END AS waiting_on
) acc ON TRUE
WHERE o.closed_at IS NULL
  AND (o.snoozed_until IS NULL OR o.snoozed_until <= now());

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verification (run after applying):
--
--   SELECT person_name, stage, hours_in_stage, hours_since_touch, waiting_on, sla_status
--   FROM lead_sla_status
--   ORDER BY hours_since_touch DESC NULLS LAST LIMIT 10;
--   -- hours_since_touch should now diverge from hours_in_stage for any lead that
--   -- has an outreach_click / contacted / outbound_messages / inbound event.
-- ─────────────────────────────────────────────────────────────────────────────
