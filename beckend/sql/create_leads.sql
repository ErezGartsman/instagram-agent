-- ─────────────────────────────────────────────────────────────────────────────
-- Phase 2 — leads table for real-time lead capture via the Telegram bot.
--
-- Dedup strategy: UNIQUE(channel, chat_id) — one stored lead per Telegram user.
-- If the same user shares their contact in a second session, ON CONFLICT DO
-- NOTHING prevents a duplicate row; the owner is never alerted twice (notified_at).
--
-- RLS is enabled immediately with zero policies (deny-all for anon, same posture
-- as all other tables). The backend (postgres / BYPASSRLS) is unaffected.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.leads (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID        REFERENCES public.sessions(id) ON DELETE SET NULL,
    chat_id        TEXT        NOT NULL,
    channel        TEXT        NOT NULL DEFAULT 'telegram',
    name           TEXT,
    phone          TEXT        NOT NULL,
    intent_summary TEXT,
    status         TEXT        NOT NULL DEFAULT 'new',
    notified_at    TIMESTAMPTZ,                      -- NULL = alert not yet sent
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One lead per Telegram user (primary dedup guard).
CREATE UNIQUE INDEX IF NOT EXISTS leads_channel_chat_uniq
    ON public.leads (channel, chat_id);

-- Fast lookup by session when checking "has this conversation already captured a lead?"
CREATE INDEX IF NOT EXISTS leads_session_idx
    ON public.leads (session_id);

-- Lock down immediately — same deny-all posture as all other tables.
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
