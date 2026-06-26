-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 002 — Autonomous Agent Runtime (Phase 1A)
-- Apply in: Supabase Dashboard → SQL Editor (or psql)
--
-- What this adds:
--   • agent_runs     — one row per agent execution; status drives the cockpit
--                      AgentPip real-time indicator via Supabase Realtime.
--   • agent_actions  — granular action log inside each run; powers the
--                      cockpit Activity Feed.
--   • info_requests  — idempotency table for outbound WhatsApp info requests;
--                      prevents the agent from double-messaging a lead.
--
-- What this does NOT add (and why):
--   • stage_transitions — already captured by the existing `interactions` table
--     with kind='stage_change' and payload JSONB {from, to, reason, by}.
--     Adding a duplicate table would create two sources of truth. Phase 2
--     analytics will query interactions WHERE kind='stage_change' instead.
--
-- Safe to run multiple times: all DDL uses IF NOT EXISTS.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── agent_runs ────────────────────────────────────────────────────────────────
-- One row per agent execution. Created at 'running' before the agent starts;
-- closed at 'success' | 'skipped' | 'failed' when it finishes.
-- Supabase Realtime watches this table → cockpit sees live status changes.

CREATE TABLE IF NOT EXISTS agent_runs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The person being evaluated. CASCADE so a person deletion cleans up.
    person_id     UUID        NOT NULL
                              REFERENCES person(id) ON DELETE CASCADE,

    -- Stable agent name used as the idempotency key (with person_id).
    -- Known values: 'qualification' | 'follow_up' | 're_engage'
    agent_type    TEXT        NOT NULL,

    -- Lifecycle: pending → running → success | skipped | failed.
    -- 'pending' is reserved for future pre-queued runs; live agents start at
    -- 'running' immediately (the idempotency guard checks both).
    status        TEXT        NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'running', 'success', 'skipped', 'failed')),

    -- What caused this run: 'stage_change' | 'cron' | 'manual'
    triggered_by  TEXT        NOT NULL,

    -- Snapshot of person/opportunity state at trigger time. Stored for
    -- debugging — lets you replay decisions without re-querying history.
    input         JSONB       NOT NULL DEFAULT '{}',

    -- Freeform result summary (what the agent decided and why).
    output        JSONB       NOT NULL DEFAULT '{}',

    -- Populated only when status='failed'.
    error         TEXT,

    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ,          -- NULL until the run closes
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index: the idempotency guard queries (person_id, agent_type, status).
CREATE INDEX IF NOT EXISTS idx_agent_runs_person_type_status
    ON agent_runs (person_id, agent_type, status);

-- Index: the cockpit "all active runs" query orders by created_at DESC.
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_desc
    ON agent_runs (created_at DESC);

-- Index: filter by agent_type for cron sweep queries.
CREATE INDEX IF NOT EXISTS idx_agent_runs_type_created
    ON agent_runs (agent_type, created_at DESC);


-- ── agent_actions ─────────────────────────────────────────────────────────────
-- Granular step log inside each run. One row per discrete action the agent
-- took (WA message sent, stage advanced, note written, etc.).
-- The cockpit Activity Feed reads this to show what the machine did.

CREATE TABLE IF NOT EXISTS agent_actions (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    agent_run_id  UUID        NOT NULL
                              REFERENCES agent_runs(id) ON DELETE CASCADE,

    -- The action taken. Known values:
    --   'whatsapp_sent'  — outbound WA message dispatched
    --   'stage_advanced' — opportunity moved forward
    --   'flag_set'       — label/flag applied to person or opportunity
    --   'note_added'     — note written to interactions log
    --   'info_requested' — info_requests row inserted
    --   'skipped'        — agent evaluated and chose to do nothing
    action_type   TEXT        NOT NULL,

    -- What was sent or changed (e.g. WA message body, stage name, flag name).
    payload       JSONB       NOT NULL DEFAULT '{}',

    -- Outcome of the action (e.g. WA message_id, advance_stage return value).
    result        JSONB       NOT NULL DEFAULT '{}',

    at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index: the Activity Feed loads all actions for a person ordered by time.
-- We join via agent_runs, so index on agent_run_id is the inner lookup.
CREATE INDEX IF NOT EXISTS idx_agent_actions_run_id
    ON agent_actions (agent_run_id, at DESC);


-- ── info_requests ─────────────────────────────────────────────────────────────
-- Tracks outbound WhatsApp messages that request missing person info.
-- The qualification agent checks this table before sending to prevent
-- double-messaging: if an unfulfilled request exists for this person within
-- the rate-limit window, the agent skips the send.

CREATE TABLE IF NOT EXISTS info_requests (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    person_id       UUID        NOT NULL
                                REFERENCES person(id) ON DELETE CASCADE,

    -- The agent_runs row that generated this request.
    agent_run_id    UUID        REFERENCES agent_runs(id) ON DELETE SET NULL,

    -- Array of field names that were missing and requested.
    -- e.g. ARRAY['goal', 'tension'] or ARRAY['phone']
    fields_missing  TEXT[]      NOT NULL DEFAULT '{}',

    -- WA message body that was sent (stored for audit / dedup display).
    message_sent    TEXT,

    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Populated when an inbound WA reply resolves the request.
    replied_at      TIMESTAMPTZ,
    fulfilled       BOOLEAN     NOT NULL DEFAULT FALSE
);

-- Index: the idempotency guard queries unfulfilled requests by person.
CREATE INDEX IF NOT EXISTS idx_info_requests_person_unfulfilled
    ON info_requests (person_id, fulfilled, sent_at DESC);


-- ── Enable Supabase Realtime on agent_runs ────────────────────────────────────
-- This makes the cockpit AgentPip component receive live status updates without
-- polling. Only agent_runs needs realtime (agent_actions are loaded on demand).
-- Run once — idempotent (adding an already-present table to the publication
-- raises a notice, not an error, in Postgres 15+).
ALTER PUBLICATION supabase_realtime ADD TABLE agent_runs;


COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verification queries — run these after applying to confirm the schema:
--
--   SELECT table_name FROM information_schema.tables
--   WHERE table_schema = 'public'
--     AND table_name IN ('agent_runs', 'agent_actions', 'info_requests');
--   -- Expected: 3 rows
--
--   SELECT indexname FROM pg_indexes
--   WHERE tablename IN ('agent_runs', 'agent_actions', 'info_requests')
--   ORDER BY tablename, indexname;
--   -- Expected: 5 indexes (3 on agent_runs, 1 on agent_actions, 1 on info_requests)
--
--   SELECT * FROM pg_publication_tables
--   WHERE pubname = 'supabase_realtime' AND tablename = 'agent_runs';
--   -- Expected: 1 row (confirms Realtime is wired)
-- ─────────────────────────────────────────────────────────────────────────────
