-- ─────────────────────────────────────────────────────────────────────────────
-- Migration 006 — add covering indexes for unindexed foreign keys
-- (performance audit, 2026-07-08).
--
-- The Supabase performance advisor flagged 21 FK constraints with no covering
-- index. An unindexed FK forces a sequential scan on the child table for every
-- referential-integrity check (parent UPDATE/DELETE) and for every join/filter on
-- the FK column. Current row counts are tiny, so this is cheap insurance that
-- prevents seq-scan regressions as the person/opportunity spine grows.
--
-- Naming: idx_<table>_<column>. All use IF NOT EXISTS so the migration is
-- idempotent. Non-CONCURRENT is fine here — the tables are small and this runs in
-- a single migration transaction.
--
-- Note: several columns are `tenant_id`, which currently holds one constant value
-- (single-operator; tenancy deferred). These indexes have low selectivity TODAY
-- but are still correct for FK maintenance and become load-bearing the moment real
-- multi-tenancy ships. No functional/behaviour change — indexes only.
-- ─────────────────────────────────────────────────────────────────────────────

-- bookings
CREATE INDEX IF NOT EXISTS idx_bookings_opportunity_id           ON public.bookings          (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_bookings_tenant_id                ON public.bookings          (tenant_id);

-- bot_events
CREATE INDEX IF NOT EXISTS idx_bot_events_session_id             ON public.bot_events        (session_id);

-- content_pieces
CREATE INDEX IF NOT EXISTS idx_content_pieces_tenant_id          ON public.content_pieces    (tenant_id);

-- erasure_log
CREATE INDEX IF NOT EXISTS idx_erasure_log_tenant_id             ON public.erasure_log       (tenant_id);

-- info_requests
CREATE INDEX IF NOT EXISTS idx_info_requests_agent_run_id        ON public.info_requests     (agent_run_id);

-- interactions
CREATE INDEX IF NOT EXISTS idx_interactions_session_id           ON public.interactions      (session_id);
CREATE INDEX IF NOT EXISTS idx_interactions_tenant_id            ON public.interactions      (tenant_id);

-- merge_candidates
CREATE INDEX IF NOT EXISTS idx_merge_candidates_person_a         ON public.merge_candidates  (person_a);
CREATE INDEX IF NOT EXISTS idx_merge_candidates_person_b         ON public.merge_candidates  (person_b);

-- operator_notes
CREATE INDEX IF NOT EXISTS idx_operator_notes_operator_id        ON public.operator_notes    (operator_id);
CREATE INDEX IF NOT EXISTS idx_operator_notes_tenant_id          ON public.operator_notes    (tenant_id);

-- operators
CREATE INDEX IF NOT EXISTS idx_operators_tenant_id               ON public.operators         (tenant_id);

-- opportunities
CREATE INDEX IF NOT EXISTS idx_opportunities_assigned_operator_id ON public.opportunities    (assigned_operator_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_lead_id             ON public.opportunities     (lead_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_tenant_id           ON public.opportunities     (tenant_id);

-- outbound_messages
CREATE INDEX IF NOT EXISTS idx_outbound_messages_opportunity_id  ON public.outbound_messages (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_tenant_id       ON public.outbound_messages (tenant_id);

-- person
CREATE INDEX IF NOT EXISTS idx_person_tenant_id                  ON public.person            (tenant_id);

-- person_profile
CREATE INDEX IF NOT EXISTS idx_person_profile_tenant_id          ON public.person_profile    (tenant_id);

-- session_summaries
CREATE INDEX IF NOT EXISTS idx_session_summaries_tenant_id       ON public.session_summaries (tenant_id);
