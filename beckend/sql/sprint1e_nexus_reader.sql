-- ─────────────────────────────────────────────────────────────────────────────
-- Sprint 1E — Security Hotfix R2: nexus_reader role
--
-- HOW THIS FIXES THE ATTACK:
--   The /api/raw_query endpoint now executes user-submitted SQL with
--   "SET LOCAL ROLE nexus_reader" inside a savepoint. nexus_reader has
--   SELECT ONLY on the 4 analytics tables. It has NO access to auth.*,
--   public.leads, public.messages, public.sessions, or knowledge_base.
--   Even if an attacker has the API token, raw_query can no longer be
--   used to exfiltrate PII or Supabase auth data.
--
-- HOW TO APPLY:
--   1. Open your Supabase project → SQL Editor.
--   2. Paste and run this entire script.
--   3. No env-var or deployment changes needed — the backend code already
--      contains the matching "SET LOCAL ROLE nexus_reader" call (Sprint 1E).
--
-- WHAT THIS DOES NOT CHANGE:
--   The application still connects as postgres for all its normal operations
--   (sessions, messages, leads, etc.). Only user-submitted SQL queries
--   (raw_query endpoint) drop to the restricted nexus_reader role.
--
-- FUTURE HARDENING (optional, next sprint):
--   For full defense-in-depth, also migrate the application connection string
--   to a dedicated nexus_app role (see the commented SQL at the bottom).
--   This removes postgres-level auth.* access entirely from the connection pool.
-- ─────────────────────────────────────────────────────────────────────────────

-- ── Step 1: Create the analytics-only reader role ─────────────────────────────
-- LOGIN = false: this role is not for direct connections, only for SET LOCAL ROLE.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nexus_reader') THEN
        CREATE ROLE nexus_reader;
    END IF;
END $$;

-- ── Step 2: Grant SELECT on analytics tables only ─────────────────────────────
-- These 4 tables are the ONLY tables the SQL editor should ever touch.
-- Deliberately omits: sessions, messages, leads, knowledge_base, app_config,
-- and all auth.*, vault.*, storage.*, realtime.* tables.
GRANT USAGE ON SCHEMA public TO nexus_reader;
GRANT SELECT ON public.posts     TO nexus_reader;
GRANT SELECT ON public.comments  TO nexus_reader;
GRANT SELECT ON public.likers    TO nexus_reader;
GRANT SELECT ON public.followers TO nexus_reader;

-- ── Step 2.5: Allow the application's connection role to assume nexus_reader ───
-- The backend connects as `postgres` and runs `SET LOCAL ROLE nexus_reader`
-- per raw query. For SET ROLE to succeed, postgres must be a MEMBER of
-- nexus_reader. On PostgreSQL 16+ the creator is auto-granted membership, but
-- we grant it explicitly so the script is correct on every version and so the
-- backend's FAIL-CLOSED guard (HTTP 500 if the role can't be assumed) never
-- trips in production. Run as the same role the app connects with.
GRANT nexus_reader TO postgres;

-- ── Step 3: RLS policies for nexus_reader ─────────────────────────────────────
-- RLS is enabled on all public tables (zero policies = deny-all for non-owners).
-- These permissive SELECT policies let nexus_reader read the analytics data.
-- NOTE: "CREATE POLICY IF NOT EXISTS" is not valid SQL; use DO block for safety.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_policies WHERE policyname = 'nexus_reader_posts') THEN
        CREATE POLICY nexus_reader_posts ON public.posts
            FOR SELECT TO nexus_reader USING (true);
    END IF;
    IF NOT EXISTS (SELECT FROM pg_policies WHERE policyname = 'nexus_reader_comments') THEN
        CREATE POLICY nexus_reader_comments ON public.comments
            FOR SELECT TO nexus_reader USING (true);
    END IF;
    IF NOT EXISTS (SELECT FROM pg_policies WHERE policyname = 'nexus_reader_likers') THEN
        CREATE POLICY nexus_reader_likers ON public.likers
            FOR SELECT TO nexus_reader USING (true);
    END IF;
    IF NOT EXISTS (SELECT FROM pg_policies WHERE policyname = 'nexus_reader_followers') THEN
        CREATE POLICY nexus_reader_followers ON public.followers
            FOR SELECT TO nexus_reader USING (true);
    END IF;
END $$;

-- ── Verification query (run after applying — should return exactly 4 rows) ────
SELECT grantee, table_name, privilege_type
FROM   information_schema.role_table_grants
WHERE  grantee = 'nexus_reader'
ORDER  BY table_name;

-- ─────────────────────────────────────────────────────────────────────────────
-- OPTIONAL FUTURE HARDENING — Full connection migration to nexus_app
--
-- Uncomment and run this block when you are ready to migrate the application's
-- DB connection away from postgres entirely. Requires updating SUPABASE_DB_URL
-- in Vercel to use nexus_app credentials afterwards.
--
-- Benefits: removes auth.*/vault.*/realtime.* read access from the connection
-- pool entirely, so even a hypothetical application-level bug can't reach them.
-- ─────────────────────────────────────────────────────────────────────────────
/*
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nexus_app') THEN
        -- Replace 'CHANGE_THIS_PASSWORD' with: openssl rand -hex 32
        CREATE ROLE nexus_app LOGIN PASSWORD 'CHANGE_THIS_PASSWORD';
    END IF;
END $$;

GRANT CONNECT ON DATABASE postgres TO nexus_app;
GRANT USAGE ON SCHEMA public TO nexus_app;

-- Analytics: SELECT only
GRANT SELECT ON public.posts, public.comments,
                public.likers, public.followers TO nexus_app;

-- App state tables: read + write
GRANT SELECT, INSERT, UPDATE ON public.sessions      TO nexus_app;
GRANT SELECT, INSERT         ON public.messages      TO nexus_app;
GRANT SELECT, INSERT, UPDATE ON public.leads         TO nexus_app;
GRANT SELECT                 ON public.knowledge_base TO nexus_app;
GRANT SELECT                 ON public.app_config    TO nexus_app;

-- nexus_app can SET LOCAL ROLE nexus_reader for raw_query execution
GRANT nexus_reader TO nexus_app;

-- RLS policies for nexus_app on all tables it accesses
DO $$
DECLARE tbl text;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['sessions','messages','leads','knowledge_base','app_config']
    LOOP
        EXECUTE format(
            'CREATE POLICY nexus_app_%1$s ON public.%1$s FOR ALL TO nexus_app
             USING (true) WITH CHECK (true)',
            tbl
        );
    END LOOP;
END $$;

-- After running this: update SUPABASE_DB_URL in Vercel to:
--   postgresql://nexus_app:CHANGE_THIS_PASSWORD@[your-pooler-host]:6543/postgres
*/
