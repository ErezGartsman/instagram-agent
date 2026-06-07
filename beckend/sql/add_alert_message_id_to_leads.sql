-- ─────────────────────────────────────────────────────────────────────────────
-- Sprint 2 — leads.alert_message_id
--
-- WHY: the Telegram lead alert is now a SINGLE evolving message. We send the
-- capture alert instantly, store the Telegram message_id here, and later EDIT
-- that same message in place to append the AI Lead Brief (instead of sending a
-- cluttered second message). The id must persist because the capture turn and
-- the brief turn are two separate webhook invocations.
--
-- TEXT (not BIGINT) to stay forgiving of Telegram id formats; NULL is fine for
-- leads captured before this column existed or where the alert failed to send.
--
-- HOW TO APPLY: paste into the Supabase SQL Editor and run.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS alert_message_id TEXT;

COMMENT ON COLUMN public.leads.alert_message_id IS
    'Telegram message_id of the capture alert, edited in place to append the Lead Brief.';
