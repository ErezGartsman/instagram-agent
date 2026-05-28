#!/usr/bin/env python3
"""
One-time ETL: Local Instagram CSV/JSON files → Supabase PostgreSQL.

Usage:
  SUPABASE_DIRECT_URL="postgresql://..." python etl/load_to_supabase.py

Use the DIRECT (non-pooler) connection string — the ETL runs long transactions
that are incompatible with pgbouncer's transaction mode pooling.
"""

import os
import sys
import csv
import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("etl")

DATABASE_URL = os.environ.get("SUPABASE_DIRECT_URL")
if not DATABASE_URL:
    sys.exit("ERROR: Set SUPABASE_DIRECT_URL environment variable to the direct PostgreSQL URL.")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> datetime | None:
    """Try multiple date formats; return UTC-aware datetime or None."""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            pass
    return None


def _parse_epoch(val) -> datetime | None:
    """Convert a Unix timestamp (int or string) to UTC-aware datetime."""
    try:
        return datetime.fromtimestamp(int(val), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


# ─── Loaders ──────────────────────────────────────────────────────────────────

def _open_csv(path: Path) -> tuple:
    """
    Open a CSV with BOM-safe encoding and auto-detected delimiter.

    - ``utf-8-sig`` silently strips the UTF-8 BOM (``\\ufeff``) that Excel
      and many Instagram scraper exports prepend to the first byte.  With plain
      ``utf-8`` that byte becomes part of the first column name, so
      ``row.get("post_shortcode")`` silently returns None and every row is
      skipped — the classic "0 rows" bug.
    - csv.Sniffer inspects the first 8 KB to pick the right delimiter
      (comma, semicolon, tab, or pipe) instead of blindly assuming comma.

    Returns ``(file_object, dialect)``.  The caller is responsible for
    closing the file (``with f:`` is the idiomatic way).
    """
    f = open(path, encoding="utf-8-sig", errors="replace", newline="")
    sample = f.read(8192)
    f.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        log.info(f"  [{path.name}] delimiter detected: {dialect.delimiter!r}")
    except csv.Error:
        dialect = csv.excel          # safe fallback: RFC 4180 comma
        log.info(f"  [{path.name}] sniffer inconclusive — using comma fallback")
    return f, dialect


def _norm(row: dict) -> dict:
    """
    Normalise every key in a DictReader row by stripping leading/trailing
    whitespace and any residual BOM character (``\\ufeff``).  Defensive against
    scrapers that include extra spaces around column names.
    """
    return {k.strip().lstrip("﻿"): v for k, v in row.items()}


def load_posts(cur) -> int:
    path = DATA_DIR / "batch_posts.csv"
    if not path.exists():
        log.warning(f"posts: {path} not found, skipping.")
        return 0

    rows, seen = [], set()
    f, dialect = _open_csv(path)
    with f:
        reader = csv.DictReader(f, dialect=dialect)
        first_row = True
        for raw_row in reader:
            row = _norm(raw_row)
            if first_row:
                log.info(f"  [batch_posts.csv] columns: {list(row.keys())}")
                first_row = False
            sc = (row.get("post_shortcode") or "").strip()
            if not sc or sc in seen:
                continue
            seen.add(sc)
            posted_at = (row.get("posted_at") or "").strip()
            rows.append((sc, posted_at, _parse_date(posted_at)))

    execute_values(
        cur,
        """
        INSERT INTO posts (post_shortcode, posted_at, posted_at_ts)
        VALUES %s
        ON CONFLICT (post_shortcode) DO UPDATE
            SET posted_at    = EXCLUDED.posted_at,
                posted_at_ts = EXCLUDED.posted_at_ts
        """,
        rows,
        page_size=500,
    )
    return len(rows)


def load_comments(cur) -> int:
    path = DATA_DIR / "batch_comments.csv"
    if not path.exists():
        log.warning(f"comments: {path} not found, skipping.")
        return 0

    rows = []
    f, dialect = _open_csv(path)
    with f:
        reader = csv.DictReader(f, dialect=dialect)
        first_row = True
        for raw_row in reader:
            row = _norm(raw_row)
            if first_row:
                log.info(f"  [batch_comments.csv] columns: {list(row.keys())}")
                first_row = False
            sc       = (row.get("post_shortcode") or "").strip()
            username = (row.get("username") or "").strip()
            comment  = (row.get("comment") or "").strip()
            # The timestamp column is named "posted_at" in most scraper exports;
            # fall back to "commented_at" / "timestamp" if present.
            raw_ts = (
                row.get("posted_at")
                or row.get("commented_at")
                or row.get("timestamp")
                or ""
            ).strip()
            if sc and username:
                rows.append((sc, username, comment, _parse_epoch(raw_ts)))

    execute_values(
        cur,
        """
        INSERT INTO comments (post_shortcode, username, comment, commented_at)
        VALUES %s
        """,
        rows,
        page_size=1000,
    )
    return len(rows)


def load_likers(cur) -> int:
    path = DATA_DIR / "batch_likers.csv"
    if not path.exists():
        log.warning(f"likers: {path} not found, skipping.")
        return 0

    rows = []
    f, dialect = _open_csv(path)
    with f:
        reader = csv.DictReader(f, dialect=dialect)
        first_row = True
        for raw_row in reader:
            row = _norm(raw_row)
            if first_row:
                log.info(f"  [batch_likers.csv] columns: {list(row.keys())}")
                first_row = False
            sc       = (row.get("post_shortcode") or "").strip()
            username = (row.get("username") or "").strip()
            if sc and username:
                rows.append((sc, username))

    execute_values(
        cur,
        "INSERT INTO likers (post_shortcode, username) VALUES %s",
        rows,
        page_size=2000,
    )
    return len(rows)


def load_followers(cur) -> int:
    """
    Instagram follower JSON format (may vary by export version):

    Version A — top-level object:
      {"string_list_data": [{"value": "username", "timestamp": 1700000000, ...}]}

    Version B — top-level array of objects (multiple files merged into one):
      [{"string_list_data": [{"value": "username", "timestamp": ...}]}]

    We handle both. Multiple files are globbed and deduplicated by username.
    """
    pattern = str(DATA_DIR / "followers_*.json")
    files = glob.glob(pattern)
    if not files:
        log.warning(f"followers: no files matching {pattern}, skipping.")
        return 0

    seen: dict[str, datetime | None] = {}

    for filepath in sorted(files):
        log.info(f"  Processing {Path(filepath).name} …")
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)

        # Normalise to a flat list of {"value": ..., "timestamp": ...} entries
        entries = []
        if isinstance(raw, list):
            # Version B: list of wrapper objects
            for obj in raw:
                entries.extend(obj.get("string_list_data", []))
        elif isinstance(raw, dict):
            # Version A: single wrapper object
            entries = raw.get("string_list_data", [])

        for entry in entries:
            username = (entry.get("value") or "").strip()
            if username and username not in seen:
                seen[username] = _parse_epoch(entry.get("timestamp"))

    if not seen:
        log.warning("followers: parsed 0 entries — check JSON structure.")
        return 0

    execute_values(
        cur,
        """
        INSERT INTO followers (username, followed_at)
        VALUES %s
        ON CONFLICT (username) DO NOTHING
        """,
        list(seen.items()),
        page_size=1000,
    )
    return len(seen)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    log.info("Connecting to Supabase (direct connection)…")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # Load in FK-safe order; TRUNCATE with CASCADE for idempotency
            log.info("Clearing existing data…")
            cur.execute("TRUNCATE followers, likers, comments, posts CASCADE")

            log.info("Loading posts…")
            n = load_posts(cur)
            log.info(f"  ✓ {n:,} posts")

            log.info("Loading comments…")
            n = load_comments(cur)
            log.info(f"  ✓ {n:,} comments")

            log.info("Loading likers…")
            n = load_likers(cur)
            log.info(f"  ✓ {n:,} likers")

            log.info("Loading followers…")
            n = load_followers(cur)
            log.info(f"  ✓ {n:,} followers")

        conn.commit()
        log.info("✓ ETL complete — all data committed.")

    except Exception:
        conn.rollback()
        log.exception("ETL failed — rolled back all changes.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run()