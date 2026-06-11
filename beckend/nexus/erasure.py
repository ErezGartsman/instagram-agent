"""
nexus.erasure — right-to-be-forgotten (Ticket 3.7). Hard-delete a person and
ALL their data in one transaction.

The FK audit (docs/NEXUS_V1_BUILD_PLAN.md + the live schema) showed that a bare
`DELETE FROM person` is NOT enough: `leads.person_id` and `sessions.person_id`
are ON DELETE SET NULL, so they (and `messages`, which cascades from `sessions`)
would be left behind holding PII. So the cascade is EXPLICIT and ORDERED:

  1. bot_events  — session-scoped telemetry (no PII; avoid dangling refs)
  2. leads       — holds phone / name / intent (SET NULL would orphan it)
  3. sessions    — CASCADES messages + session_summaries (the conversation body)
  4. person      — CASCADES identity / profile / opportunities / bookings /
                   interactions / operator_notes / merge_candidates

A row is written to erasure_log (UUID + counts only, no PII) as proof the
request was honored. Commit-free: the caller owns the transaction, so any
failure rolls the whole thing back — erasure is all-or-nothing, never partial.

No crypto-shredding: because operational state lives in normal mutable tables
(not an append-only event log), erasure is a clean cascade DELETE — the payoff
of the relational-over-event-sourcing decision made in the architecture phase.
"""

import json
import logging

logger = logging.getLogger("nexus.erasure")


def erase_person(conn, person_id: str, *, requested_by: str = "api") -> dict | None:
    """
    Erase a person and all their data. Commit-free. Returns per-table deleted
    counts on success, or None if the person does not exist (idempotent: an
    already-erased person is a no-op None).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM person WHERE id = %s", (person_id,))
        if cur.fetchone() is None:
            return None

        # Session ids drive the bot_events delete and the messages count.
        cur.execute("SELECT id FROM sessions WHERE person_id = %s", (person_id,))
        session_ids = [r[0] for r in cur.fetchall()]

        # Count everything that will be removed (the cascaded tables can't be
        # counted from rowcount after the fact) — one round-trip for the log.
        cur.execute(
            "SELECT "
            " (SELECT count(*) FROM messages WHERE session_id = ANY(%s)), "
            " (SELECT count(*) FROM person_identity WHERE person_id = %s), "
            " (SELECT count(*) FROM person_profile WHERE person_id = %s), "
            " (SELECT count(*) FROM session_summaries WHERE person_id = %s), "
            " (SELECT count(*) FROM operator_notes WHERE person_id = %s), "
            " (SELECT count(*) FROM opportunities WHERE person_id = %s), "
            " (SELECT count(*) FROM bookings WHERE person_id = %s), "
            " (SELECT count(*) FROM interactions WHERE person_id = %s), "
            " (SELECT count(*) FROM merge_candidates "
            "  WHERE person_a = %s OR person_b = %s)",
            (session_ids, person_id, person_id, person_id, person_id,
             person_id, person_id, person_id, person_id, person_id))
        c = cur.fetchone()
        counts = {
            "messages": c[0], "person_identity": c[1], "person_profile": c[2],
            "session_summaries": c[3], "operator_notes": c[4],
            "opportunities": c[5], "bookings": c[6], "interactions": c[7],
            "merge_candidates": c[8],
        }

        # Ordered hard deletes (steps 1-4).
        cur.execute("DELETE FROM bot_events WHERE session_id = ANY(%s)", (session_ids,))
        counts["bot_events"] = cur.rowcount
        cur.execute("DELETE FROM leads WHERE person_id = %s", (person_id,))
        counts["leads"] = cur.rowcount
        cur.execute("DELETE FROM sessions WHERE person_id = %s", (person_id,))
        counts["sessions"] = cur.rowcount     # cascades messages + session_summaries
        cur.execute("DELETE FROM person WHERE id = %s", (person_id,))
        counts["person"] = cur.rowcount       # cascades the eight child tables

        # Proof-of-erasure (no PII — UUID + counts only).
        cur.execute(
            "INSERT INTO erasure_log (erased_person_id, deleted_counts, requested_by) "
            "VALUES (%s, %s::jsonb, %s)",
            (person_id, json.dumps(counts), requested_by))

    logger.info("[erasure] person %s erased: %s", person_id, counts)
    return counts
