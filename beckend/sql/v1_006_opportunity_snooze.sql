-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 006: opportunity snooze (the Work Queue Action Loop)
--
-- WHY: the cockpit Work Queue gains the Action Loop — the operator works the
-- queue and "handles" or "snoozes" a lead to take it off TODAY's list WITHOUT
-- closing the pipeline opportunity. A nullable snoozed_until timestamp does this
-- with zero new tables and no funnel-stage pollution: the lead stays OPEN
-- (closed_at IS NULL) but the queue hides it until the time passes. "Done"
-- (handled today → a short cool-off) and "Snooze" (explicit defer) share this
-- one column, differing only in default duration and the logged interaction kind
-- (handled vs snoozed). "Dismiss" is the only action that actually closes (lost).
--
-- Additive + idempotent — safe to re-run; no backfill needed (NULL = not snoozed).
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.opportunities
    ADD COLUMN IF NOT EXISTS snoozed_until TIMESTAMPTZ;

-- The Work Queue filters "open AND not currently snoozed", so a partial index on
-- snoozed_until over open rows keeps that predicate cheap.
CREATE INDEX IF NOT EXISTS opportunities_snooze_idx
    ON public.opportunities (snoozed_until) WHERE closed_at IS NULL;
