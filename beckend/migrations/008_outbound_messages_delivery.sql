-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 008 — One Thread Phase 2: delivery lifecycle + idempotency for
-- outbound_messages (docs/ONE_THREAD_PRD.md §3.2).
--
-- WHY: outbound_messages (migration 007) recorded a confirmed send with no
-- delivery state and no protection against a double-click/retry sending the
-- same WhatsApp message twice. Phase 2 wires a real send-from-cockpit
-- composer, so both become necessary:
--
--   status          — queued→sent→delivered→read→failed lifecycle. Existing
--                      rows (all successful sends to date) default to 'sent',
--                      which is already correct for them — no backfill needed.
--   failure_reason   — surfaces WHY a send failed in the composer UI, instead
--                      of a bare "send failed".
--   provider         — which rail actually carried the message (kapso today;
--                      meta_ig / telegram land in Phase 3) — audit trail.
--   send_target      — the exact address sent to (phone/igsid/chat_id) —
--                      debugging aid, independent of whatever's currently in
--                      person_identity (which can change later).
--   client_token      — a per-send-attempt token the frontend generates once
--                      and replays on retry. The partial unique index makes a
--                      repeat INSERT with the same token a no-op instead of a
--                      second message reaching the lead.
--
-- Additive + idempotent, same posture as every other Nexus migration. No
-- application code depends on these columns until Phase 2 ships alongside it.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.outbound_messages
    ADD COLUMN IF NOT EXISTS status         TEXT NOT NULL DEFAULT 'sent',
    ADD COLUMN IF NOT EXISTS failure_reason TEXT,
    ADD COLUMN IF NOT EXISTS provider       TEXT,
    ADD COLUMN IF NOT EXISTS send_target    TEXT,
    ADD COLUMN IF NOT EXISTS client_token   TEXT;

-- One row per client_token — NULL (all pre-Phase-2 rows, and any future caller
-- that doesn't supply one) is never considered a duplicate under a unique index.
CREATE UNIQUE INDEX IF NOT EXISTS outbound_messages_client_token_uniq
    ON public.outbound_messages (client_token) WHERE client_token IS NOT NULL;
