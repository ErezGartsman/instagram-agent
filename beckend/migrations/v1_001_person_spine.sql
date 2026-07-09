-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 001: the Person spine (identity layer)
--
-- WHY: today identity is (channel, chat_id), so the same human on Instagram,
-- Telegram and WhatsApp is three unrelated rows and cross-channel memory is
-- impossible. This migration introduces the canonical Person entity that every
-- session, lead, interaction, booking and memory record will hang off.
--
-- This file contains ONLY the V1 irreversibles agreed in the build plan
-- (docs/NEXUS_V1_BUILD_PLAN.md): tenancy + operator hedge columns, person,
-- person_identity, merge_candidates, and person_id links on sessions/leads.
-- Flow tables (interactions/opportunities/bookings) are migration 002; memory
-- tables (person_profile/session_summaries/operator_notes) are migration 003.
--
-- DESIGN DECISIONS ENCODED HERE:
--   • tenant_id on every root table, defaulted to the single seeded tenant —
--     multi-tenancy stays a column, not a feature (cheap-irreversibility hedge).
--   • person_identity UNIQUE(channel, external_id) — one handle maps to exactly
--     one person. 'phone' is itself an identity channel, which makes phone the
--     deterministic cross-channel join key (Telegram capture ↔ Calendly invitee).
--   • NO auto-merge: when a phone arrives that already belongs to a different
--     person, code writes a merge_candidates row for manual review in the
--     cockpit. Wrong merges cross-contaminate intimate context — operator only.
--   • Persons are created ONLY on funnel entry (IG/TG DM) or capture (web).
--     NEVER from the content tables (followers/likers/comments) — 20k followers
--     must not become 20k person records (privacy + noise).
--   • RLS enabled deny-all on all new tables, same posture as every existing
--     table (backend connects as postgres / BYPASSRLS).
--
-- STATUS: applied to the live Nexus DB via the Supabase MCP (2026-06-10),
-- after build approval. This file is the record. Idempotent / safe to re-run.
--
-- AFTER APPLYING (required, Sprint 3 ticket 3.7): add the new tables to
-- _INTERNAL_TABLES in main.py so the NL2SQL schema description can never see
-- them, and verify nexus_reader has no grants:
--   SELECT table_name FROM information_schema.role_table_grants
--   WHERE grantee = 'nexus_reader' AND table_schema = 'public';
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Tenancy + operators (the cheap hedges — columns now, features never/later) ─

CREATE TABLE IF NOT EXISTS public.tenants (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Single seeded tenant. All tenant_id columns default to this id so application
-- code never has to think about tenancy until the day it becomes a feature.
INSERT INTO public.tenants (id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'nexus-primary')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.operators (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                             REFERENCES public.tenants(id),
    email        TEXT        NOT NULL UNIQUE,
    display_name TEXT        NOT NULL,
    role         TEXT        NOT NULL DEFAULT 'owner',   -- owner|assistant (validated in code)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cockpit login allowlist seed. This must match the email Erez signs into the
-- cockpit with (Supabase Auth) — update here if a different address is used.
INSERT INTO public.operators (email, display_name)
VALUES ('erezkim1234@gmail.com', 'Erez Gartsman')
ON CONFLICT (email) DO NOTHING;

-- ── Person — the canonical human across channels ──────────────────────────────

CREATE TABLE IF NOT EXISTS public.person (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                 REFERENCES public.tenants(id),
    display_name     TEXT,
    primary_language TEXT        NOT NULL DEFAULT 'he',
    -- Coarse person-level stage, derived in code from opportunities:
    -- audience | lead | booked | client | dormant. TEXT not ENUM (bot_state
    -- precedent) so new stages need no migration.
    lifecycle_stage  TEXT        NOT NULL DEFAULT 'audience',
    -- Short ref code embedded in the wa.me prefill text so a WhatsApp arrival
    -- can be linked back to this person manually in the cockpit (WhatsApp
    -- conversations themselves stay out-of-system in V1).
    wa_ref_code      TEXT        UNIQUE,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.person IS
  'Canonical human across all channels. Created on funnel entry (IG/TG) or at '
  'capture (web) — never from content tables. Deleting a person cascades to '
  'identities/memory/opportunities/bookings (erasure path).';

CREATE TABLE IF NOT EXISTS public.person_identity (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id   UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    -- channel ∈ instagram | telegram | web | phone | email | whatsapp
    -- (validated in code; phone external_id is normalized E.164).
    channel     TEXT        NOT NULL,
    external_id TEXT        NOT NULL,
    username    TEXT,                      -- @handle where the channel has one (IG)
    -- deterministic = exact platform id / phone; manual = operator-linked
    -- (e.g. wa_ref_code); inferred = reserved for V2+ (never auto-merged on).
    confidence  TEXT        NOT NULL DEFAULT 'deterministic',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One handle → exactly one person. This is the identity-resolution backbone.
CREATE UNIQUE INDEX IF NOT EXISTS person_identity_channel_ext_uniq
    ON public.person_identity (channel, external_id);

CREATE INDEX IF NOT EXISTS person_identity_person_idx
    ON public.person_identity (person_id);

-- ── Merge candidates — duplicates are surfaced, never auto-merged ─────────────

CREATE TABLE IF NOT EXISTS public.merge_candidates (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    person_a    UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    person_b    UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    reason      TEXT        NOT NULL,                 -- e.g. 'shared_phone'
    status      TEXT        NOT NULL DEFAULT 'open',  -- open|merged|dismissed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    CHECK (person_a <> person_b)
);

-- At most one OPEN candidate per unordered pair — keeps the review queue clean.
CREATE UNIQUE INDEX IF NOT EXISTS merge_candidates_open_pair_uniq
    ON public.merge_candidates (LEAST(person_a, person_b), GREATEST(person_a, person_b))
    WHERE status = 'open';

-- ── Link existing tables to the spine ─────────────────────────────────────────
-- ON DELETE SET NULL keeps the migration safe; the erasure endpoint deletes
-- sessions/messages/leads rows explicitly (they hold PII) before the person row.

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS person_id UUID
    REFERENCES public.person(id) ON DELETE SET NULL;
ALTER TABLE public.leads    ADD COLUMN IF NOT EXISTS person_id UUID
    REFERENCES public.person(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS sessions_person_idx ON public.sessions (person_id);
CREATE INDEX IF NOT EXISTS leads_person_idx    ON public.leads (person_id);

-- ── Lock down — same deny-all posture as every other table ────────────────────

ALTER TABLE public.tenants          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operators        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.person           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.person_identity  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.merge_candidates ENABLE ROW LEVEL SECURITY;
