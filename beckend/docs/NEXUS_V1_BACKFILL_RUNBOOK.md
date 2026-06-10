# NEXUS V1 — Backfill runbook (ticket 3.4)

Maps all historical leads / sessions / bot_events onto the person spine using
`etl/backfill_person_spine.py`. The script reuses the live nexus primitives,
runs as ONE transaction, is dry-run by default, and is idempotent — a second
`--execute` run reports zeros. Full safety model in the script header.

A production dry-run was already executed on 2026-06-10 (transaction rolled
back): expect ~41 persons created, 7 leads + ~35 sessions stamped,
6 opportunities, ~24 backfill interactions, and **3 merge candidates** —
see step 5.

## 1. Pre-flight (1 minute)

```powershell
cd "<repo>\beckend"
$line = Get-Content .env | Where-Object { $_ -match '^SUPABASE_DB_URL=' } | Select-Object -First 1
$env:SUPABASE_DIRECT_URL = $line.Substring('SUPABASE_DB_URL='.Length).Trim('"')
```

The bot can stay live — the script is concurrency-safe (same unique indexes
that arbitrate the live hooks). No deploy is required; the script runs from
your machine against the live DB.

## 2. Dry-run

```powershell
.\venv\Scripts\python.exe etl\backfill_person_spine.py
```

Read the output: `BEFORE` / `AFTER` snapshots, `STATS`, created person ids.
It ends with `DRY-RUN — rolled back`. Sanity expectations: `leads_unstamped`
and `sessions_unstamped` go to 0 in AFTER; `persons_wo_wa_ref` stays 0.

## 3. Execute

```powershell
.\venv\Scripts\python.exe etl\backfill_person_spine.py --execute
```

Ends with `✓ COMMITTED.` — KEEP THE OUTPUT (the created-person-id list is the
reversal handle).

## 4. Verify (Supabase SQL editor)

```sql
-- all zero:
SELECT
  (SELECT COUNT(*) FROM leads WHERE person_id IS NULL)        AS leads_unstamped,
  (SELECT COUNT(*) FROM sessions WHERE person_id IS NULL
     AND channel IN ('telegram','instagram')
     AND contact_id IS NOT NULL)                              AS sessions_unstamped,
  (SELECT COUNT(*) FROM person WHERE wa_ref_code IS NULL)     AS persons_wo_wa_ref;

-- the spine, eyeballed:
SELECT p.display_name, p.lifecycle_stage, pi.channel, pi.external_id
FROM person p JOIN person_identity pi ON pi.person_id = p.id
ORDER BY p.created_at DESC LIMIT 30;

-- historical timeline landed at historical timestamps:
SELECT kind, channel, occurred_at, source FROM interactions
WHERE source = 'backfill' ORDER BY occurred_at;
```

## 5. Review the merge candidates (expected: 3)

```sql
SELECT mc.id, mc.reason, mc.status,
       a.display_name AS person_a_name, b.display_name AS person_b_name
FROM merge_candidates mc
JOIN person a ON a.id = mc.person_a
JOIN person b ON b.id = mc.person_b
WHERE mc.status = 'open';
```

The dry-run queued 3 `shared_phone` candidates — almost certainly Erez's own
test accounts (Telegram + Instagram smoke tests using the same real phone).
The system refuses to auto-merge intimate context on a shared phone; resolving
them is a cockpit feature (Sprint 4). Until then they can stay open harmlessly,
or be dismissed manually:
`UPDATE merge_candidates SET status='dismissed', resolved_at=NOW() WHERE id='…';`

## 6. Idempotency proof

Run `--execute` again: STATS shows zeros (`persons_created: 0`,
`leads_stamped: 0`, …). That output is the proof the script is re-runnable.

## 7. Reversal (if ever needed)

Person deletion cascades identities / opportunities / interactions / profile:

```sql
DELETE FROM person WHERE id IN ('<ids from the run output>');
-- plus the telemetry replay rows, which carry their own tag:
DELETE FROM interactions WHERE source = 'backfill';
```
