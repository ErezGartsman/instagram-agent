# Migrations — the single numbered home

All schema changes live here, ordered by `MANIFEST.txt` (not by filename), and
tracked in the `public.schema_migrations` ledger by `scripts/migrate.py`:

```
python scripts/migrate.py status     # ledger vs manifest
python scripts/migrate.py apply      # run pending, one transaction each
```

History: the `v1_*` files (person spine era, Sprint 3) originally lived in
`beckend/sql/` and the numeric files here — consolidated 2026-07-09 (E0,
SYSTEM_ELEVATION_PRD.md). Everything through `008` was applied by hand via the
Supabase MCP before the runner existed and is recorded in the ledger with
`baselined = TRUE`. The remaining files in `beckend/sql/` are the pre-V1 ad-hoc
era (leads table, RLS enablement, analytics views) — records only, not managed
by the runner.

Rules (unchanged from the v1 era):
- idempotent DDL (`IF NOT EXISTS`) — the ledger prevents re-runs, idempotence keeps accidents boring
- RLS deny-all on every new table (backend connects as postgres / BYPASSRLS)
- new tables get added to `_INTERNAL_TABLES` in main.py (NL2SQL must never see them)
- files are the record: applied SQL is never edited, only appended to
