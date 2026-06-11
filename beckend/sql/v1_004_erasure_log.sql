-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 004: erasure_log (right-to-be-forgotten audit trail)
--
-- Proof that a deletion request was honored, WITHOUT retaining any PII. Stores
-- only the deleted person's UUID + per-table row counts + who/when. Crucially
-- there is NO foreign key to person (the person is being deleted) and no name,
-- phone, email, or message content — so this row is GDPR-safe to keep forever
-- and is unlinkable to a human once the person is gone.
--
-- RLS deny-all (backend = postgres / BYPASSRLS), same posture as every table.
-- Added to _INTERNAL_TABLES in main.py so the NL2SQL engine can never see it.
--
-- STATUS: applied to the live Nexus DB via the Supabase MCP (2026-06-11).
-- Idempotent / safe to re-run.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.erasure_log (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                 REFERENCES public.tenants(id),
    erased_person_id UUID        NOT NULL,        -- intentionally NO FK (person is gone)
    deleted_counts   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    requested_by     TEXT,
    erased_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.erasure_log ENABLE ROW LEVEL SECURITY;
