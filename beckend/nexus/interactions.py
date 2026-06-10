"""
nexus.interactions — the append-only signal log + the opportunity stage machine.

interactions is signal CAPTURE, not event-sourcing: normal mutable tables
(person/opportunities/bookings) remain operational truth; this log is the
parallel record powering the Person-360 timeline, audit, and future
derivation. payload carries small refs/flags only (message ids, stage
from/to) — NEVER message bodies (PII discipline; verbatim text stays in the
messages table).

The opportunity stage machine is forward-only and idempotent: webhook retries
and duplicate funnel events are harmless no-ops. Stage transitions are
audited as interaction kind='stage_change', which is why no separate
transitions table exists.
"""

import json
import logging

from nexus import db

logger = logging.getLogger("nexus.interactions")

INTERACTION_KINDS = {
    "session_started", "icebreaker_hit", "trigger_hit", "qualified", "captured",
    "context_provided", "stage_change", "booking_created", "booking_canceled",
    "outreach_click", "contacted", "note_added", "merged", "alert_sent",
    "crm_synced", "formation_run",
}

# Forward-only pipeline. 'booked' may be reached from any open stage (a lead
# can jump straight from engaged to a Calendly booking).
PIPELINE_STAGES = ("engaged", "qualified", "captured", "briefed", "booked")
TERMINAL_STAGES = ("done", "lost")

# person.lifecycle_stage is a coarse person-level derivation of pipeline state.
_LIFECYCLE_BY_STAGE = {
    "qualified": "lead",
    "captured":  "lead",
    "briefed":   "lead",
    "booked":    "booked",
    "done":      "client",
}


def stage_is_forward(current: str, to: str) -> bool:
    """
    True when `to` is a strictly later pipeline stage than `current`.
    Unknown stages are never forward (fail-closed).
    """
    if current not in PIPELINE_STAGES or to not in PIPELINE_STAGES:
        return False
    return PIPELINE_STAGES.index(to) > PIPELINE_STAGES.index(current)


def log_interaction(
    conn,
    kind: str,
    channel: str,
    *,
    person_id: str | None = None,
    session_id: str | None = None,
    payload: dict | None = None,
    dedup_key: str | None = None,
    source: str = "live",
) -> bool:
    """
    INSERT one signal row. Commit-free — the caller owns the transaction.
    Returns False when dedup_key already exists (idempotent ingest), True
    when the row was written.
    """
    if kind not in INTERACTION_KINDS:
        raise ValueError(f"unknown interaction kind {kind!r}")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO interactions "
            "(kind, channel, person_id, session_id, payload, source, dedup_key) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s) ON CONFLICT DO NOTHING",
            (kind, channel, person_id, session_id,
             json.dumps(payload or {}, ensure_ascii=False, default=str),
             source, dedup_key),
        )
        return cur.rowcount == 1


def track(kind: str, channel: str, **kwargs) -> None:
    """
    Best-effort standalone wrapper for hot bot paths: own pooled connection,
    own commit, NEVER raises — a signal-log failure must not break a webhook
    turn (same contract as _track in main.py).
    """
    try:
        with db.get_conn() as conn:
            log_interaction(conn, kind, channel, **kwargs)
            conn.commit()
    except Exception as e:
        logger.warning("[interactions] track %r failed: %s", kind, e)


def get_or_open_opportunity(conn, person_id: str, source_channel: str) -> str:
    """
    Return the person's open opportunity id, creating one at 'engaged' when
    none exists. Race-safe under the one-open-per-person partial unique
    index (the loser of a creation race adopts the winner's row). Commit-free.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM opportunities WHERE person_id = %s AND closed_at IS NULL",
            (person_id,),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        cur.execute(
            "INSERT INTO opportunities (person_id, source_channel) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id",
            (person_id, source_channel),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT id FROM opportunities "
                "WHERE person_id = %s AND closed_at IS NULL",
                (person_id,),
            )
            row = cur.fetchone()
        return str(row[0])


def advance_stage(
    conn,
    opportunity_id: str,
    to_stage: str,
    *,
    reason: str | None = None,
    by: str = "system",
) -> bool:
    """
    Move an open opportunity forward. Forward-only: repeats and regressions
    are silent no-ops, so webhook retries and duplicate funnel events are
    harmless. Updates the derived person.lifecycle_stage and logs the
    transition as interaction kind='stage_change'. Returns True only when
    the stage actually changed. Commit-free.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id, stage, source_channel, closed_at "
            "FROM opportunities WHERE id = %s",
            (opportunity_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        person_id, current, source_channel, closed_at = \
            str(row[0]), row[1], row[2], row[3]
        if closed_at is not None or not stage_is_forward(current, to_stage):
            return False
        cur.execute(
            "UPDATE opportunities SET stage = %s, stage_entered_at = NOW(), "
            "updated_at = NOW() WHERE id = %s",
            (to_stage, opportunity_id),
        )
        lifecycle = _LIFECYCLE_BY_STAGE.get(to_stage)
        if lifecycle:
            cur.execute(
                "UPDATE person SET lifecycle_stage = %s, updated_at = NOW() "
                "WHERE id = %s",
                (lifecycle, person_id),
            )
    log_interaction(
        conn, "stage_change", source_channel or "system", person_id=person_id,
        payload={"opportunity_id": opportunity_id, "from": current,
                 "to": to_stage, "reason": reason, "by": by},
    )
    return True


def close_opportunity(
    conn,
    opportunity_id: str,
    outcome: str,
    *,
    reason: str | None = None,
    by: str = "system",
) -> bool:
    """
    Close an open opportunity at 'done' (consultation happened) or 'lost'
    (incl. staleness auto-close). Idempotent: closing an already-closed
    opportunity is a no-op. Commit-free.
    """
    if outcome not in TERMINAL_STAGES:
        raise ValueError(f"invalid close outcome {outcome!r}")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id, stage, source_channel FROM opportunities "
            "WHERE id = %s AND closed_at IS NULL",
            (opportunity_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        person_id, current, source_channel = str(row[0]), row[1], row[2]
        cur.execute(
            "UPDATE opportunities SET stage = %s, closed_at = NOW(), "
            "close_reason = %s, stage_entered_at = NOW(), updated_at = NOW() "
            "WHERE id = %s",
            (outcome, reason, opportunity_id),
        )
        if outcome == "done":
            cur.execute(
                "UPDATE person SET lifecycle_stage = 'client', updated_at = NOW() "
                "WHERE id = %s",
                (person_id,),
            )
    log_interaction(
        conn, "stage_change", source_channel or "system", person_id=person_id,
        payload={"opportunity_id": opportunity_id, "from": current,
                 "to": outcome, "reason": reason, "by": by},
    )
    return True
