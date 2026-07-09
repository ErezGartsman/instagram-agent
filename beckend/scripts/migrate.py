"""
migrate.py — the Nexus migration runner (E0, SYSTEM_ELEVATION_PRD.md §Blind Spot 7).

One numbered home (beckend/migrations/), one explicit order (MANIFEST.txt),
one ledger table (public.schema_migrations). Replaces the apply-by-hand-via-MCP
ritual whose record was split across beckend/sql/ and beckend/migrations/.

Commands
    python scripts/migrate.py status              # ledger vs manifest
    python scripts/migrate.py baseline            # mark ALL manifest entries applied (no SQL run)
    python scripts/migrate.py apply               # run pending entries, in manifest order
    python scripts/migrate.py apply --dry-run     # show what would run

Rules
  • MANIFEST.txt is the order of record — lexicographic filename order is NOT
    trusted (the v1_* era predates the numeric era).
  • `baseline` exists because everything through 008 is already live in prod:
    run it once, then only `apply` forever after.
  • Files must stay idempotent (IF NOT EXISTS) like every migration to date —
    the ledger prevents re-runs, idempotence keeps accidents boring.
  • Connection = SUPABASE_DB_URL (env, falling back to beckend/.env).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

BECKEND = Path(__file__).resolve().parent.parent
MIGRATIONS = BECKEND / "migrations"
MANIFEST = MIGRATIONS / "MANIFEST.txt"

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version    TEXT        PRIMARY KEY,      -- manifest filename
    checksum   TEXT        NOT NULL,         -- sha256 of the file at apply time
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    baselined  BOOLEAN     NOT NULL DEFAULT FALSE
);
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
"""


def _db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        env = BECKEND / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SUPABASE_DB_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not url:
        sys.exit("SUPABASE_DB_URL not set (env or beckend/.env)")
    return url


def _manifest() -> list[Path]:
    if not MANIFEST.exists():
        sys.exit(f"manifest missing: {MANIFEST}")
    files = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = MIGRATIONS / line
        if not p.exists():
            sys.exit(f"manifest entry missing on disk: {line}")
        files.append(p)
    return files


def _checksum(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _ledger(cur) -> dict[str, str]:
    cur.execute(LEDGER_DDL)
    cur.execute("SELECT version, checksum FROM public.schema_migrations")
    return dict(cur.fetchall())


def cmd_status(conn) -> None:
    files = _manifest()
    with conn.cursor() as cur:
        applied = _ledger(cur)
    conn.commit()
    pending = 0
    for p in files:
        if p.name in applied:
            drift = "" if applied[p.name] == _checksum(p) else "  [checksum drift]"
            print(f"  applied  {p.name}{drift}")
        else:
            pending += 1
            print(f"  PENDING  {p.name}")
    print(f"\n{len(files) - pending} applied, {pending} pending")


def cmd_baseline(conn) -> None:
    files = _manifest()
    with conn.cursor() as cur:
        applied = _ledger(cur)
        n = 0
        for p in files:
            if p.name in applied:
                continue
            cur.execute(
                "INSERT INTO public.schema_migrations (version, checksum, baselined) "
                "VALUES (%s, %s, TRUE) ON CONFLICT (version) DO NOTHING",
                (p.name, _checksum(p)),
            )
            n += 1
    conn.commit()
    print(f"baselined {n} migrations ({datetime.now(timezone.utc).isoformat()})")


def cmd_apply(conn, dry_run: bool) -> None:
    files = _manifest()
    with conn.cursor() as cur:
        applied = _ledger(cur)
    conn.commit()
    pending = [p for p in files if p.name not in applied]
    if not pending:
        print("nothing pending")
        return
    for p in pending:
        if dry_run:
            print(f"would apply {p.name}")
            continue
        sql = p.read_text(encoding="utf-8")
        print(f"applying {p.name} …", end=" ", flush=True)
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO public.schema_migrations (version, checksum) VALUES (%s, %s)",
                (p.name, _checksum(p)),
            )
        conn.commit()   # one transaction per migration — a failure stops the train
        print("ok")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["status", "baseline", "apply"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(_db_url())
    try:
        if args.command == "status":
            cmd_status(conn)
        elif args.command == "baseline":
            cmd_baseline(conn)
        else:
            cmd_apply(conn, args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
