-- ─────────────────────────────────────────────────────────────────────────────
-- Phase 2b — bot_state column for the 2-turn lead-qualification state machine.
--
-- Drives the conversational flow in the Telegram webhook:
--   NULL                     → normal conversation
--   'awaiting_qualification' → qualification question was sent; the next user
--                              message is treated as the topic reply and the
--                              contact-share keyboard is shown in response.
--
-- The column is TEXT (not an ENUM) so new states can be added without a
-- migration. The backend always treats any unrecognised value as NULL.
--
-- Applied to the Nexus DB via the Supabase management API before this commit.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS bot_state TEXT;

COMMENT ON COLUMN public.sessions.bot_state IS
  'Telegram bot state machine. NULL = normal. ''awaiting_qualification'' = '
  'qualification question sent; next user reply triggers the contact keyboard.';
