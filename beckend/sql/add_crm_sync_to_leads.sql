-- ─────────────────────────────────────────────────────────────────────────────
-- Sprint 1B — vendor-neutral CRM sync state on the leads table.
--
-- Supabase is the source of truth; a CRM (HubSpot today) is a downstream
-- projection behind a swappable adapter. These columns track the sync:
--   crm_synced_at IS NULL  → lead not yet pushed to the CRM (capture-time
--                            failure, CRM disabled at the time, or new row).
--   crm_synced_at SET      → contact upserted; crm_external_id holds the CRM id.
--
-- The reconciliation endpoint /api/cron/crm-sync selects rows WHERE
-- crm_synced_at IS NULL and retries them; the partial index keeps that cheap.
--
-- Idempotent + forward-compatible: if an earlier draft created vendor-specific
-- columns (ghl_contact_id / ghl_synced_at), they are renamed in place so no data
-- is lost; on a fresh database the columns are simply created.
--
-- Applied to the Nexus DB via the Supabase management API before this commit.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    -- Rename the earlier GHL-specific columns to the vendor-neutral names when
    -- they exist and the new names don't (handles the live Nexus DB).
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='leads'
                 AND column_name='ghl_contact_id')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='leads'
                 AND column_name='crm_external_id') THEN
        ALTER TABLE public.leads RENAME COLUMN ghl_contact_id TO crm_external_id;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='leads'
                 AND column_name='ghl_synced_at')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='leads'
                 AND column_name='crm_synced_at') THEN
        ALTER TABLE public.leads RENAME COLUMN ghl_synced_at TO crm_synced_at;
    END IF;
END $$;

-- Create on a fresh DB (no-op if the rename above already produced them).
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS crm_external_id TEXT;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS crm_synced_at  TIMESTAMPTZ;

-- Rebuild the reconciliation work-queue index against the new column name.
DROP INDEX IF EXISTS leads_unsynced_idx;
CREATE INDEX IF NOT EXISTS leads_unsynced_idx
    ON public.leads (created_at)
    WHERE crm_synced_at IS NULL;

COMMENT ON COLUMN public.leads.crm_external_id IS
  'External CRM record id (e.g. HubSpot contact id). NULL until first sync.';
COMMENT ON COLUMN public.leads.crm_synced_at IS
  'Timestamp of successful CRM sync. NULL = pending; retried by /api/cron/crm-sync.';
