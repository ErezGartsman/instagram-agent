-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 002: flow layer (interactions, opportunities, bookings)
--
-- WHY: the cockpit's three core reads — the Person-360 timeline, the pipeline
-- kanban, and the north-star metric — all need durable flow state that today
-- lives implicitly in bot_state strings, Telegram messages and nowhere at all.
--
--   • interactions   — the append-only signal log. NOT event-sourcing: normal
--     mutable tables remain operational truth; this is a parallel record for
--     timeline + audit + future derivation. payload holds small refs/flags
--     (message ids, stage from/to) — NEVER message bodies (PII discipline).
--     kinds (validated in code): session_started, icebreaker_hit, trigger_hit,
--     qualified, captured, context_provided, stage_change, booking_created,
--     booking_canceled, outreach_click, contacted, note_added, merged,
--     alert_sent, crm_synced, formation_run.
--
--   • opportunities  — one pipeline episode per person toward a booking.
--     Stages (validated in code, forward-only): engaged → qualified → captured
--     → briefed → booked, terminal done|lost. Partial unique index enforces at
--     most ONE OPEN episode per person; a person can accumulate closed episodes
--     over months (person is permanent, opportunity is episodic).
--     Stage transitions are audited as interaction kind='stage_change'.
--
--   • bookings       — the north star made observable. Sourced from the
--     Calendly webhook (external_id = invitee uuid, idempotent) or manual
--     cockpit entry. person_id stays NULL until matched (phone → email →
--     manual via the cockpit's unlinked-bookings inbox).
--
-- STATUS: applied to the live Nexus DB via the Supabase MCP (2026-06-10).
-- This file is the record. Idempotent / safe to re-run.
--
-- AFTER APPLYING (Sprint 3 ticket 3.7): add interactions, opportunities,
-- bookings to _INTERNAL_TABLES in main.py (NL2SQL must never see them).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.interactions (
    id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                            REFERENCES public.tenants(id),
    person_id   UUID        REFERENCES public.person(id)   ON DELETE CASCADE,
    session_id  UUID        REFERENCES public.sessions(id) ON DELETE SET NULL,
    channel     TEXT        NOT NULL,
    kind        TEXT        NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    source      TEXT        NOT NULL DEFAULT 'live',    -- live|backfill|manual
    dedup_key   TEXT                                    -- idempotent ingest guard
);

CREATE UNIQUE INDEX IF NOT EXISTS interactions_dedup_uniq
    ON public.interactions (dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS interactions_person_ts_idx
    ON public.interactions (person_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS interactions_kind_ts_idx
    ON public.interactions (kind, occurred_at DESC);

CREATE TABLE IF NOT EXISTS public.opportunities (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                     REFERENCES public.tenants(id),
    person_id            UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    lead_id              UUID        REFERENCES public.leads(id) ON DELETE SET NULL,
    stage                TEXT        NOT NULL DEFAULT 'engaged',
    stage_entered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    opened_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at            TIMESTAMPTZ,
    close_reason         TEXT,
    source_channel       TEXT,
    assigned_operator_id UUID        REFERENCES public.operators(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- At most one open pipeline episode per person — re-engagement after a closed
-- episode opens a fresh opportunity instead of resurrecting the old one.
CREATE UNIQUE INDEX IF NOT EXISTS opportunities_one_open_per_person
    ON public.opportunities (person_id) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS opportunities_open_stage_idx
    ON public.opportunities (stage) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS public.bookings (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                               REFERENCES public.tenants(id),
    person_id      UUID        REFERENCES public.person(id) ON DELETE CASCADE,
    opportunity_id UUID        REFERENCES public.opportunities(id) ON DELETE SET NULL,
    source         TEXT        NOT NULL,                       -- calendly|manual
    external_id    TEXT,                                       -- Calendly invitee uuid
    starts_at      TIMESTAMPTZ,
    status         TEXT        NOT NULL DEFAULT 'scheduled',   -- scheduled|canceled|completed|no_show
    invitee_name   TEXT,
    invitee_phone  TEXT,
    invitee_email  TEXT,
    matched_via    TEXT,                                       -- phone|email|manual|none
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS bookings_external_uniq
    ON public.bookings (external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS bookings_person_idx ON public.bookings (person_id);
CREATE INDEX IF NOT EXISTS bookings_starts_idx ON public.bookings (starts_at);

-- Same deny-all posture as every other table (backend = postgres / BYPASSRLS).
ALTER TABLE public.interactions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bookings      ENABLE ROW LEVEL SECURITY;
