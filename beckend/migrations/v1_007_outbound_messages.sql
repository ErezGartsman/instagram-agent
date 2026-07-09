-- ─────────────────────────────────────────────────────────────────────────────
-- NEXUS V1 — Migration 007: outbound_messages (the cockpit Action Loop · Send)
--
-- WHY: the "Send message" action gives the cockpit a voice. We need an audit
-- trail of what the OPERATOR sent — distinct from the lead's INBOUND conversation,
-- which stays deliberately out-of-system (the PII lock). Storing our own outbound
-- words is a different, lower-risk posture than storing the lead's intimate inbound
-- text. The interactions log stays ref-only (`{message_id}`); the verbatim body
-- lives here.
--
-- Additive + idempotent. Service-role-only like the rest of the spine (the FastAPI
-- auth gate fronts all access; no public PostgREST surface) — RLS on, no policy.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.outbound_messages (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'
                                     REFERENCES public.tenants(id),
    person_id            UUID        NOT NULL REFERENCES public.person(id) ON DELETE CASCADE,
    opportunity_id       UUID        REFERENCES public.opportunities(id) ON DELETE SET NULL,
    channel              TEXT        NOT NULL DEFAULT 'whatsapp',
    body                 TEXT        NOT NULL,                  -- verbatim, operator-authored
    provider_message_id  TEXT,                                  -- wamid from Kapso/Meta
    sent_by              TEXT,                                  -- operator email (cockpit JWT)
    sent_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS outbound_messages_person_ts_idx
    ON public.outbound_messages (person_id, sent_at DESC);

ALTER TABLE public.outbound_messages ENABLE ROW LEVEL SECURITY;
