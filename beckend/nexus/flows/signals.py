"""
nexus.flows.signals — the live-state snapshot condition nodes and the
state-trigger dispatcher both reason about. One query, one shape, matching
nexus.flows.predicates.FIELD_REGISTRY field-for-field.

Deliberately independent of nexus.work_queue's ranking signals — the Work
Queue and Flows read the same live opportunity/interaction state, but nothing
here shares a cache with the Work Queue; each computes fresh. Commit-free.
"""
from __future__ import annotations

import datetime
from collections.abc import Iterator


def open_opportunity_signals(
    conn,
) -> Iterator[tuple[str, str, datetime.datetime, dict]]:
    """Yield (person_id, opportunity_id, stage_entered_at, signals) for every
    OPEN opportunity. `signals` keys match predicates.FIELD_REGISTRY exactly."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT o.person_id, o.id, o.stage, o.stage_entered_at, o.source_channel, "
            "       EXTRACT(EPOCH FROM (NOW() - li.last_at)) / 3600.0, "
            "       EXTRACT(EPOCH FROM (NOW() - o.stage_entered_at)) / 3600.0 "
            "FROM opportunities o "
            "LEFT JOIN (SELECT person_id, MAX(occurred_at) AS last_at "
            "           FROM interactions GROUP BY person_id) li "
            "       ON li.person_id = o.person_id "
            "WHERE o.closed_at IS NULL"
        )
        rows = cur.fetchall()
    for (person_id, opp_id, stage, stage_entered_at, channel,
         hours_since_last, hours_in_stage) in rows:
        signals = {
            "stage":             stage,
            "hours_since_last":  float(hours_since_last) if hours_since_last is not None else None,
            "hours_in_stage":    float(hours_in_stage) if hours_in_stage is not None else None,
            "channel":           channel,
            "urgency":           None,   # reserved — not yet joined in V1
            "waiting_on":        None,   # reserved — not yet joined in V1
        }
        yield str(person_id), str(opp_id), stage_entered_at, signals


def signals_for(conn, person_id: str) -> dict | None:
    """Signals for one person's open opportunity, with `opportunity_id`
    folded in. None when they have no open opportunity (e.g. an event fired
    for a person whose opportunity just closed) — callers must treat that as
    'no live state to condition on', not an error."""
    for pid, opp_id, _stage_entered_at, signals in open_opportunity_signals(conn):
        if pid == person_id:
            return {**signals, "opportunity_id": opp_id}
    return None
