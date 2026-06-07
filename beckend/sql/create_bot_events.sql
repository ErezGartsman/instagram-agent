-- ─────────────────────────────────────────────────────────────────────────────
-- Sprint 2 — bot_events: lightweight conversion telemetry
--
-- WHY: _audit() writes to a logfile that is ephemeral on Vercel serverless, so
-- it cannot power conversion metrics over time. This table persists the funnel
-- hinges (icebreaker_hit, lead_captured) so /api/metrics can compute the
-- icebreaker→capture conversion rate.
--
-- PRIVACY: no raw PII. We reference session_id only — never phone numbers, IGSIDs,
-- or message bodies. `meta` holds small non-identifying flags (e.g. lead_id,
-- returning_lead).
--
-- HOW TO APPLY: paste into the Supabase SQL Editor and run.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.bot_events (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel    TEXT        NOT NULL,                       -- 'instagram' | 'telegram' | …
    event      TEXT        NOT NULL,                       -- 'icebreaker_hit' | 'lead_captured'
    session_id UUID        REFERENCES public.sessions(id) ON DELETE SET NULL,
    meta       JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- Fast metric aggregation by event over a time window, and per-channel filter.
CREATE INDEX IF NOT EXISTS bot_events_event_ts_idx   ON public.bot_events (event, ts DESC);
CREATE INDEX IF NOT EXISTS bot_events_channel_ts_idx ON public.bot_events (channel, ts DESC);

-- Same deny-all posture as every other table. The backend connects as postgres
-- (BYPASSRLS); the analytics-only nexus_reader role is deliberately NOT granted
-- access here, so /api/raw_query can never read telemetry.
ALTER TABLE public.bot_events ENABLE ROW LEVEL SECURITY;
