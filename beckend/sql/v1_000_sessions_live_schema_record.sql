-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 000: RECORD of pre-existing live sessions schema
--
-- WHY: the integration audit (docs/NEXUS_V1_INTEGRATION_MAP.md, finding #4)
-- found live schema on public.sessions that was applied historically via the
-- management API and never recorded in sql/. Per the V1 schema-discipline
-- rule (no unrecorded schema), this file records it. Object names below match
-- the LIVE database exactly (verified via pg_indexes / information_schema on
-- 2026-06-10), so every statement is a no-op on the live DB — IF NOT EXISTS
-- checks NAMES, which is why guessing names would have created duplicates.
--
-- NUMBERED 000: it logically precedes v1_001 (it records what was already
-- true before the V1 work began).
--
-- Also RECORDED here but NOT changed: public.sessions still carries a legacy
-- `ghl_contact_id` (varchar) column from the abandoned GoHighLevel draft
-- (see sql/add_crm_sync_to_leads.sql for the rename history on leads).
-- Dropping it is a separate, deliberate cleanup decision — not a side effect
-- of a record file.
--
-- STATUS: applied to the live Nexus DB via the Supabase MCP (2026-06-10) as a
-- verified no-op, so the migration ledger is complete. Idempotent.
-- ─────────────────────────────────────────────────────────────────────────────

-- The race-safe get-or-create in _db_get_or_create_channel_session relies on
-- this unique index (INSERT … ON CONFLICT (channel, contact_id) DO NOTHING).
CREATE UNIQUE INDEX IF NOT EXISTS sessions_channel_contact_uniq
    ON public.sessions (channel, contact_id);

-- bot_state TTL companion column (see _db_get_session_state / _db_set_session_state).
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS bot_state_expires_at TIMESTAMPTZ;

-- Recent-session and contact lookups.
CREATE INDEX IF NOT EXISTS idx_sessions_active  ON public.sessions (last_active DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_contact ON public.sessions (contact_id);
