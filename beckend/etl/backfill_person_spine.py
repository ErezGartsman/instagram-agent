#!/usr/bin/env python3
"""
NEXUS V1 — Ticket 3.4: backfill the person spine from historical data.

Maps every pre-spine lead, session and bot_event onto the person /
person_identity / opportunities / interactions ontology, exactly as the live
hooks (nexus/hooks.py) would have written them — by REUSING the same tested
primitives (nexus.identity, nexus.interactions), not reimplementing them.

SAFETY MODEL
  • DRY-RUN BY DEFAULT: the full pass runs inside one transaction, prints the
    summary, then ROLLS BACK. Nothing persists until --execute.
  • ONE TRANSACTION: a mid-run failure rolls back everything — there is no
    partial state to "resume from"; you simply run it again.
  • IDEMPOTENT BY CONSTRUCTION (safe to re-run after a successful --execute):
      person_identity  UNIQUE(channel, external_id)      → resolve, not dup
      leads/sessions   ... WHERE person_id IS NULL        → stamp once
      opportunities    one-open-per-person partial index  → ON CONFLICT skip
      interactions     dedup_key (captured:<lead_id> — the SAME key Hook B
                       uses live, so post-deploy captures are not duplicated;
                       bot_event:<id> for telemetry rows)  → insert once
      wa_ref_code      ... WHERE wa_ref_code IS NULL      → assign once
    A second --execute run reports zeros across the board.
  • CONCURRENCY-SAFE: the live bot can keep capturing during the run — the
    same unique indexes that make the hooks race-safe arbitrate here too.
  • REVERSAL: created person ids are printed; DELETE FROM person WHERE id
    IN (...) cascades identities/opportunities/interactions/profile cleanly.

USAGE
    SUPABASE_DIRECT_URL="postgresql://..." python etl/backfill_person_spine.py            # dry-run
    SUPABASE_DIRECT_URL="postgresql://..." python etl/backfill_person_spine.py --execute  # commit

(SUPABASE_DB_URL is accepted as a fallback env var.)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# The script lives in etl/ but reuses the nexus package one level up.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

from nexus import identity, interactions  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

DATABASE_URL = os.environ.get("SUPABASE_DIRECT_URL") or os.environ.get("SUPABASE_DB_URL")
if not DATABASE_URL:
    sys.exit("ERROR: set SUPABASE_DIRECT_URL (or SUPABASE_DB_URL).")

# Persons are only ever created from funnel channels — never from content
# tables (followers/likers), and web sessions stay person-less until capture.
SPINE_CHANNELS = ("telegram", "instagram")


def snapshot(cur) -> dict:
    """Counts that tell the whole before/after story in one glance."""
    counts = {}
    for label, sql in [
        ("persons",            "SELECT COUNT(*) FROM person"),
        ("identities",         "SELECT COUNT(*) FROM person_identity"),
        ("phone_identities",   "SELECT COUNT(*) FROM person_identity WHERE channel='phone'"),
        ("persons_wo_wa_ref",  "SELECT COUNT(*) FROM person WHERE wa_ref_code IS NULL"),
        ("leads_unstamped",    "SELECT COUNT(*) FROM leads WHERE person_id IS NULL"),
        ("sessions_unstamped", "SELECT COUNT(*) FROM sessions WHERE person_id IS NULL "
                               "AND channel IN ('telegram','instagram') "
                               "AND contact_id IS NOT NULL"),
        ("opportunities",      "SELECT COUNT(*) FROM opportunities"),
        ("backfill_rows",      "SELECT COUNT(*) FROM interactions WHERE source='backfill'"),
        ("merge_candidates",   "SELECT COUNT(*) FROM merge_candidates WHERE status='open'"),
    ]:
        cur.execute(sql)
        counts[label] = cur.fetchone()[0]
    return counts


def backfill_leads(conn, stats: dict, created_persons: list) -> None:
    """
    Leads are the richest source (name + phone), so they go first. Each lead
    becomes: person + channel identity + phone identity + person stamps on
    the lead and its session + a 'captured' opportunity + the canonical
    captured interaction at the lead's historical timestamp.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, session_id, chat_id, channel, name, phone, created_at "
            "FROM leads ORDER BY created_at"
        )
        leads = cur.fetchall()

    for lead_id, session_id, chat_id, channel, name, phone, created_at in leads:
        lead_id = str(lead_id)
        if channel not in SPINE_CHANNELS:
            stats["leads_skipped_channel"] += 1
            continue

        person_id, created = identity.resolve_or_create_person(
            conn, channel, chat_id, display_name=name
        )
        if created:
            created_persons.append(person_id)
            stats["persons_created"] += 1

        link = identity.attach_phone_identity(conn, person_id, phone)
        stats[f"phone_{link}"] += 1

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE leads SET person_id = %s "
                "WHERE id = %s AND person_id IS NULL",
                (person_id, lead_id),
            )
            stats["leads_stamped"] += cur.rowcount
            if session_id:
                cur.execute(
                    "UPDATE sessions SET person_id = %s "
                    "WHERE id = %s AND person_id IS NULL",
                    (person_id, str(session_id)),
                )
            # Coarse derived stage — never downgrade a booked/client person.
            cur.execute(
                "UPDATE person SET lifecycle_stage = 'lead' "
                "WHERE id = %s AND lifecycle_stage = 'audience'",
                (person_id,),
            )
            # Historical episode at its real timestamps. The one-open-per-
            # person partial index makes this a no-op when the live hooks
            # (or a previous run) already opened one.
            cur.execute(
                "INSERT INTO opportunities "
                "(person_id, stage, stage_entered_at, opened_at, source_channel) "
                "VALUES (%s, 'captured', %s, %s, %s) "
                "ON CONFLICT (person_id) WHERE closed_at IS NULL DO NOTHING",
                (person_id, created_at, created_at, channel),
            )
            stats["opportunities_created"] += cur.rowcount

        wrote = interactions.log_interaction(
            conn, "captured", channel,
            person_id=person_id,
            session_id=str(session_id) if session_id else None,
            payload={"lead_id": lead_id, "phone_link": link},
            dedup_key=f"captured:{lead_id}",      # same key Hook B uses live
            source="backfill",
            occurred_at=created_at,
        )
        stats["captured_interactions"] += int(wrote)


def backfill_sessions(conn, stats: dict, created_persons: list) -> None:
    """Sessions without a lead still become persons (they talked to the bot)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, channel, contact_id FROM sessions "
            "WHERE channel IN %s AND contact_id IS NOT NULL "
            "AND person_id IS NULL ORDER BY created_at",
            (SPINE_CHANNELS,),
        )
        rows = cur.fetchall()

    for session_id, channel, contact_id in rows:
        person_id, created = identity.resolve_or_create_person(conn, channel, contact_id)
        if created:
            created_persons.append(person_id)
            stats["persons_created"] += 1
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET person_id = %s "
                "WHERE id = %s AND person_id IS NULL",
                (person_id, str(session_id)),
            )
            stats["sessions_stamped"] += cur.rowcount


def backfill_bot_events(conn, stats: dict) -> None:
    """
    Replay funnel telemetry into the interactions timeline at historical
    timestamps. lead_captured events are deliberately SKIPPED — the leads pass
    already wrote the canonical captured:<lead_id> row.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT be.id, be.ts, be.channel, be.event, be.session_id, be.meta, "
            "       s.person_id "
            "FROM bot_events be LEFT JOIN sessions s ON s.id = be.session_id "
            "WHERE be.event IN ('icebreaker_hit', 'context_provided') "
            "ORDER BY be.id"
        )
        rows = cur.fetchall()

    for event_id, ts, channel, event, session_id, meta, person_id in rows:
        meta = meta or {}
        kind = ("trigger_hit"
                if event == "icebreaker_hit" and meta.get("entry") == "trigger_word"
                else event)
        wrote = interactions.log_interaction(
            conn, kind, channel,
            person_id=str(person_id) if person_id else None,
            session_id=str(session_id) if session_id else None,
            payload={k: v for k, v in meta.items() if k != "lead_id"},
            dedup_key=f"bot_event:{event_id}",
            source="backfill",
            occurred_at=ts,
        )
        stats["telemetry_interactions"] += int(wrote)


def assign_wa_refs(conn, stats: dict) -> None:
    """
    Every person gets a wa_ref_code so the WhatsApp CTA prefill (Hook D) can
    link them the moment that path goes live. Collision odds at this scale are
    ~zero (31^6 code space); the UNIQUE constraint is the final guard.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM person WHERE wa_ref_code IS NULL")
        ids = [str(r[0]) for r in cur.fetchall()]
        for pid in ids:
            cur.execute(
                "UPDATE person SET wa_ref_code = %s WHERE id = %s",
                (identity.generate_wa_ref(), pid),
            )
        stats["wa_refs_assigned"] = len(ids)


def refresh_seen_timestamps(conn) -> None:
    """first/last_seen should reflect history, not the backfill run time."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE person p SET "
            "  first_seen_at = LEAST(p.first_seen_at, agg.min_created), "
            "  last_seen_at  = GREATEST(p.last_seen_at, agg.max_active) "
            "FROM (SELECT person_id, MIN(created_at) AS min_created, "
            "             MAX(COALESCE(last_active, created_at)) AS max_active "
            "      FROM sessions WHERE person_id IS NOT NULL "
            "      GROUP BY person_id) agg "
            "WHERE agg.person_id = p.id"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill the NEXUS person spine.")
    parser.add_argument("--execute", action="store_true",
                        help="COMMIT the changes (default is dry-run + rollback).")
    args = parser.parse_args()

    from collections import defaultdict
    stats: dict = defaultdict(int)
    created_persons: list[str] = []

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            before = snapshot(cur)
        log.info("BEFORE: %s", dict(before))

        backfill_leads(conn, stats, created_persons)
        backfill_sessions(conn, stats, created_persons)
        backfill_bot_events(conn, stats)
        assign_wa_refs(conn, stats)
        refresh_seen_timestamps(conn)

        with conn.cursor() as cur:
            after = snapshot(cur)
        log.info("AFTER:  %s", dict(after))
        log.info("STATS:  %s", dict(stats))
        if created_persons:
            log.info("CREATED person ids (reversal: DELETE FROM person WHERE id IN ...):")
            for pid in created_persons:
                log.info("  %s", pid)
        if after["merge_candidates"] > before["merge_candidates"]:
            log.warning("New merge candidates were queued (shared phone across "
                        "channels) — review them in the cockpit / Supabase.")

        if args.execute:
            conn.commit()
            log.info("✓ COMMITTED.")
        else:
            conn.rollback()
            log.info("DRY-RUN — rolled back. Re-run with --execute to commit.")
    except Exception:
        conn.rollback()
        log.exception("Backfill failed — rolled back, nothing persisted.")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
