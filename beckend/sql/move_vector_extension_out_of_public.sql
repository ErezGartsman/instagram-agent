-- ─────────────────────────────────────────────────────────────────────────────
-- Security hardening — move the pgvector extension out of the `public` schema.
--
-- WHY: the Supabase security advisor flags extensions installed in `public`
-- (lint 0014_extension_in_public) — objects in public are broadly accessible,
-- so extensions belong in a dedicated `extensions` schema.
--
-- SAFE because `extensions` is already in the role search_path
-- ("$user", public, extensions), so existing `::vector` casts and the
-- knowledge_base.embedding column keep resolving (the type OID does not change).
--
-- STATUS: already applied to the live Nexus project (verified: vector now in
-- `extensions`, `::vector` cast works, all 3 knowledge_base embeddings intact,
-- the `<=>` cosine operator used by _retrieve_chunks still works). This file is
-- the migration record.
--
-- HOW TO APPLY (idempotent): paste into the Supabase SQL Editor and run.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension e
        JOIN pg_namespace n ON e.extnamespace = n.oid
        WHERE e.extname = 'vector' AND n.nspname = 'public'
    ) THEN
        ALTER EXTENSION vector SET SCHEMA extensions;
    END IF;
END $$;
