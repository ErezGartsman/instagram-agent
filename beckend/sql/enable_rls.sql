-- ─────────────────────────────────────────────────────────────────────────────
-- Phase 1.5 — Row Level Security lockdown for the Nexus database.
--
-- GOAL: permit NO anonymous frontend access. Every public table is exposed to
-- the Supabase `anon` / `authenticated` roles (anon key) by default; this file
-- closes that door.
--
-- HOW IT WORKS:
--   * ENABLE ROW LEVEL SECURITY + zero policies  =  deny-all for anon /
--     authenticated. With no policy, those roles can see/modify no rows.
--   * The backend connects as the `postgres` role, which OWNS every table and
--     has BYPASSRLS, so it is completely unaffected and keeps full access.
--
-- WHY NOT `FORCE ROW LEVEL SECURITY`:
--   FORCE would apply RLS to the table owner too. With no policies defined that
--   would lock out the backend (postgres) and take production down. We rely on
--   the owner/BYPASSRLS exemption, so plain ENABLE is exactly right.
--
-- REVERSIBLE: ALTER TABLE <t> DISABLE ROW LEVEL SECURITY;
--
-- NOTE: this is a deny-by-default posture. If we later want the frontend to
-- talk to Supabase directly (it currently goes through the FastAPI backend),
-- we add explicit, least-privilege policies per table — never blanket access.
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE public.posts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.comments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.likers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.followers      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_base ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_config     ENABLE ROW LEVEL SECURITY;
