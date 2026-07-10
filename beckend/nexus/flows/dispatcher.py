"""
nexus.flows.dispatcher — turns raw signal into flow_runs rows
(SYSTEM_ELEVATION_PRD.md §B3: "the dispatcher sweep... IS the outbox — no
dual-write problem").

Two independent sweeps, both idempotent via flow_runs.dedup_key so a sweep
that dies partway (or races a concurrent sweep) is harmless to re-run:

  dispatch_events(conn) — EVENT triggers: new `interactions` rows past a
    stored watermark (app_config), matched against published flows whose
    trigger is {"type":"event","kind":"<interaction kind>"}. dedup_key =
    "event:<flow_id>:<interaction_id>" — the interactions log IS the outbox,
    so replay is a schema-level no-op via the UNIQUE dedup_key, not hope.

  dispatch_states(conn) — STATE triggers: every OPEN opportunity's live
    signals, matched against published flows' predicate (nexus.flows.
    predicates). dedup_key = "state:<flow_id>:<person_id>:<stage_entered_at>"
    — opportunities.stage_entered_at is the natural "condition-episode"
    boundary the PRD calls for, so a state flow fires once per stage-entry,
    not once per sweep while the condition holds.

Feedback-loop guard (PRD Blind Spot #3): an EVENT-triggered interaction whose
payload carries causation ("caused_by_flow_depth") at depth >= 2 is skipped —
a flow that sends → a reply → a flow that sends again is fine (depth 1); a
third hop is refused. State triggers have no causation chain to check (they
react to durable opportunity state, not a single interaction), so this guard
only applies to dispatch_events. NOTE: the read-side guard is live here; the
write-side (tagging an inbound reply as caused-by-a-flow-send) is deferred
until a flow can actually send for real (F1 ships every seeded flow in
shadow mode — see runner.py) — there is nothing to tag yet, and wiring it
blind, unverifiable against a real send, would be speculative plumbing.

Commit-free — the sweep endpoint owns the transaction (one commit per phase,
so a failure in the state sweep never rolls back events already dispatched).
"""
from __future__ import annotations

import json
import logging

from nexus.flows import policy as flow_policy
from nexus.flows import predicates as flow_predicates
from nexus.flows import signals as flow_signals

logger = logging.getLogger("nexus.flows.dispatcher")

_WATERMARK_CONFIG_KEY = "flows.dispatch_watermark"   # app_config value: interactions.id as text
_MAX_CAUSATION_DEPTH = 2   # an interaction caused at this depth or deeper never re-triggers


def dispatch_events(conn, *, limit: int = 500) -> int:
    """Event-trigger sweep. Returns the number of flow_runs inserted."""
    if not flow_policy.flows_enabled():
        return 0
    flows = _published_flows(conn, "event")
    if not flows:
        return 0

    watermark = _get_watermark(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, person_id, kind, payload FROM interactions "
            "WHERE id > %s AND person_id IS NOT NULL "
            "ORDER BY id ASC LIMIT %s",
            (watermark, limit),
        )
        rows = cur.fetchall()

    inserted = 0
    max_id = watermark
    for interaction_id, person_id, kind, payload in rows:
        max_id = max(max_id, interaction_id)
        depth = _causation_depth(payload)
        for flow in flows:
            if flow["trigger"].get("kind") != kind:
                continue
            if depth >= _MAX_CAUSATION_DEPTH:
                logger.info(
                    "[dispatcher] skipping flow=%s interaction=%s — causation depth %d >= %d",
                    flow["slug"], interaction_id, depth, _MAX_CAUSATION_DEPTH,
                )
                continue
            dedup_key = f"event:{flow['id']}:{interaction_id}"
            if _insert_run(conn, flow, str(person_id), dedup_key,
                           trigger_interaction_id=interaction_id, causation_depth=depth):
                inserted += 1

    if max_id != watermark:
        _set_watermark(conn, max_id)
    return inserted


def dispatch_states(conn) -> int:
    """State-trigger sweep. Returns the number of flow_runs inserted."""
    if not flow_policy.flows_enabled():
        return 0
    flows = _published_flows(conn, "state")
    if not flows:
        return 0

    inserted = 0
    for flow in flows:
        predicate = flow["trigger"].get("predicate")
        if not predicate:
            logger.error("[dispatcher] flow=%s has a state trigger with no predicate", flow["slug"])
            continue
        try:
            flow_predicates.validate(predicate)
        except flow_predicates.PredicateError as e:
            logger.error("[dispatcher] flow=%s has an invalid state predicate: %s", flow["slug"], e)
            continue

        for person_id, opportunity_id, stage_entered_at, signal_values in flow_signals.open_opportunity_signals(conn):
            try:
                matched = flow_predicates.evaluate(predicate, signal_values)
            except flow_predicates.PredicateError as e:
                logger.error("[dispatcher] flow=%s predicate eval failed: %s", flow["slug"], e)
                break   # same predicate will fail for every person — stop wasting the sweep
            if not matched:
                continue
            dedup_key = f"state:{flow['id']}:{person_id}:{stage_entered_at.isoformat()}"
            if _insert_run(conn, flow, person_id, dedup_key, opportunity_id=opportunity_id):
                inserted += 1
    return inserted


# ── Internals ─────────────────────────────────────────────────────────────────

def _published_flows(conn, trigger_type: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug, live, trigger, graph FROM flow_definitions "
            "WHERE status = 'published' AND trigger->>'type' = %s",
            (trigger_type,),
        )
        rows = cur.fetchall()
    return [
        {"id": str(r[0]), "slug": r[1], "live": r[2], "trigger": r[3], "graph": r[4]}
        for r in rows
    ]


def _causation_depth(payload) -> int:
    if isinstance(payload, dict):
        return int(payload.get("caused_by_flow_depth") or 0)
    return 0


def _insert_run(
    conn, flow: dict, person_id: str, dedup_key: str, *,
    trigger_interaction_id=None, opportunity_id=None, causation_depth: int = 0,
) -> bool:
    context = {"opportunity_id": opportunity_id} if opportunity_id else {}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO flow_runs "
            "(flow_id, person_id, trigger_interaction_id, status, context, "
            " causation_depth, dedup_key) "
            "VALUES (%s, %s, %s, 'running', %s::jsonb, %s, %s) "
            "ON CONFLICT (dedup_key) DO NOTHING",
            (flow["id"], person_id, trigger_interaction_id,
             json.dumps(context, default=str), causation_depth, dedup_key),
        )
        return cur.rowcount == 1


def _get_watermark(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM app_config WHERE key = %s", (_WATERMARK_CONFIG_KEY,))
        row = cur.fetchone()
    try:
        return int(row[0]) if row and row[0] else 0
    except (TypeError, ValueError):
        return 0


def _set_watermark(conn, value: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_config (key, value, description) "
            "VALUES (%s, %s, 'Flows dispatcher watermark — last interactions.id processed') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (_WATERMARK_CONFIG_KEY, str(value)),
        )
