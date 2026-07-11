-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 010 — Flows authoring (Phase F3, SYSTEM_ELEVATION_PRD.md §F3)
--
-- WHY: F3 opens flow_definitions to editing + simulation-gated publishing.
-- Two additive columns:
--   • updated_at      — draft edits touch it; the canvas shows "edited 2h ago".
--   • last_simulation — the 90-day simulation report that gated the most
--     recent publish (nexus/flows/simulate.py's output). Stored ON the row so
--     "published after simulating: would have fired 34×, 6 blocked" is an
--     auditable fact, not a transient dialog. NULL until first published via
--     the gate; the two seeded flows (published pre-F3) simply have NULL.
--
-- No new tables — F3 authoring reuses flow_definitions' existing status
-- machine (draft→published→paused→archived) and version column. Editing a
-- published flow creates a NEW draft row at version+1 (application logic in
-- nexus/flows/authoring.py); published rows stay immutable, exactly as the
-- 009 header promised ("Editing a flow creates a new version row … published
-- rows stay immutable").
--
-- Additive + idempotent. RLS unchanged (deny-all; backend = postgres).
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

ALTER TABLE public.flow_definitions
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS last_simulation JSONB;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verification:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'flow_definitions'
--     AND column_name IN ('updated_at', 'last_simulation');
--   -- Expected: 2 rows
-- ─────────────────────────────────────────────────────────────────────────────
