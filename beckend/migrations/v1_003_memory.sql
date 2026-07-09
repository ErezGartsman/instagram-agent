-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 003: the memory layer (light memory, V1)
--
-- The "understand a person over time" store. Three tables, all hanging off the
-- person spine, all RLS deny-all (backend = postgres / BYPASSRLS), all already
-- in _INTERNAL_TABLES so the NL2SQL engine can never see them.
--
--   • person_profile     — ONE row per person: a Hebrew narrative summary +
--     structured attributes + a facts list with provenance. The hot-loaded
--     context for recall (V2). version/model_version make every derivation
--     re-derivable; updated_by guards operator edits from AI overwrites.
--
--   • session_summaries  — ONE row per conversation: episodic memory. The
--     `sensitive` flag marks crisis/self-harm sessions whose CONTENT is never
--     stored (neutral one-liner only) — the M4 governance rule, enforced in
--     nexus/memory.py.
--
--   • operator_notes     — Erez's own manual notes (first-class memory, never
--     touched by AI patches). Empty until the cockpit (Sprint 4); created now
--     so the schema is complete and the merge logic can preserve operator data.
--
-- NO vector columns in V1 — recall is profile + recent summaries injected into
-- the prompt. Embeddings/vector recall are a V2 migration when conversation
-- volume justifies it (the reason gemini-embedding-001 dimensionality and an
-- embedding_version column are deferred, not forgotten).
--
-- STATUS: applied to the live Nexus DB via the Supabase MCP (2026-06-10).
-- This file is the record. Idempotent / safe to re-run.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.person_profile (
    person_id     UUID        PRIMARY KEY REFERENCES public.person(id) ON DELETE CASCADE,
    tenant_id     UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                              REFERENCES public.tenants(id),
    summary       TEXT,                                   -- Hebrew narrative (hot context)
    attributes    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    facts         JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- [{fact, by, session_id, at}]
    version       INT         NOT NULL DEFAULT 1,
    model_version TEXT,
    updated_by    TEXT        NOT NULL DEFAULT 'ai',        -- ai | operator
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.session_summaries (
    session_id      UUID        PRIMARY KEY REFERENCES public.sessions(id) ON DELETE CASCADE,
    person_id       UUID        REFERENCES public.person(id) ON DELETE CASCADE,
    tenant_id       UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                REFERENCES public.tenants(id),
    summary         TEXT        NOT NULL,
    topic           TEXT,
    emotional_state TEXT,
    urgency         INT,
    sensitive       BOOLEAN     NOT NULL DEFAULT FALSE,    -- crisis session → content NOT stored
    model_version   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS session_summaries_person_idx
    ON public.session_summaries (person_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.operator_notes (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                            REFERENCES public.tenants(id),
    person_id   UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    operator_id UUID        REFERENCES public.operators(id),
    body        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS operator_notes_person_idx
    ON public.operator_notes (person_id, created_at DESC);

ALTER TABLE public.person_profile    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_summaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operator_notes    ENABLE ROW LEVEL SECURITY;
