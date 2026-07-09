-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 005: the Content Studio (Sprint 5, the Studio pillar)
--
-- WHY: Nexus is the all-in-one operating system, and the Studio pillar brings
-- the content engine into the same OS as the CRM — "the logic behind the magic."
-- This table is the durable store for Erez's video scripts and content themes
-- (deep emotional dynamics, self-worth, no clichés), managed from the cockpit's
-- rail + Fraunces-canvas Content Studio.
--
--   • content_pieces — one row per script/idea. status is forward-ish but freely
--     editable: idea → drafting → published (validated in code, TEXT not ENUM so
--     new states need no migration). theme_tags is a plain text array.
--     leads_attributed is the MANUAL "logic behind the magic" bridge for V1
--     (NULL = unknown/hidden); true automatic content→lead attribution is a V2
--     problem — we never fabricate the number.
--
-- STATUS: NOT yet applied. Apply via the Supabase MCP BEFORE enabling
-- VITE_FEATURE_CONTENT in production. Idempotent / safe to re-run. The cockpit
-- works in dev without it (the Studio uses sample data under the auth bypass).
--
-- AFTER APPLYING: content_pieces is already added to _INTERNAL_TABLES in main.py
-- (NL2SQL must never see it).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.content_pieces (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                 REFERENCES public.tenants(id),
    title            TEXT        NOT NULL DEFAULT '',
    body             TEXT        NOT NULL DEFAULT '',
    status           TEXT        NOT NULL DEFAULT 'idea',   -- idea | drafting | published
    theme_tags       TEXT[]      NOT NULL DEFAULT '{}',
    leads_attributed INT,                                   -- manual V1; NULL = hidden (auto = V2)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS content_pieces_status_idx
    ON public.content_pieces (status, updated_at DESC);

-- Same deny-all posture as every other table (backend = postgres / BYPASSRLS).
ALTER TABLE public.content_pieces ENABLE ROW LEVEL SECURITY;
