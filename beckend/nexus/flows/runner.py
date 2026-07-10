"""
nexus.flows.runner — walks flow_runs from cursor_node to completion
(SYSTEM_ELEVATION_PRD.md §B3-B4).

Reconciliation, not a daemon: one sweep claims every run in status='running'
(FOR UPDATE SKIP LOCKED — safe under a concurrent sweep), executes nodes
until it hits a wait/terminal/failure, and returns. A cheap timer pass first
resumes any 'waiting' run whose flow_timers row has fired.

Node executors are a plain dict dispatch table — never arbitrary code (PRD
§B8 non-goal: "No arbitrary code nodes"). Every step is written to
flow_run_steps before the cursor advances — a run is reconstructable
node-by-node even if the process dies mid-sweep (the next sweep just re-claims
it and continues from cursor_node).

SHADOW MODE (F1): action:send_message / action:notify_operator check
run['flow_live'] (flow_definitions.live, joined at claim time) — when false,
they log a 'shadow' step describing exactly what they would have done and
perform NO real side effect. Neither of F1's two seeded flows is live. This
is the mechanism, not a convention: there is no code path here that sends for
real when live=false, so a config typo elsewhere cannot silently start
messaging leads.
"""
from __future__ import annotations

import datetime
import json
import logging

from nexus import interactions as nexus_interactions
from nexus.flows import memory as flow_memory
from nexus.flows import policy as flow_policy
from nexus.flows import predicates as flow_predicates
from nexus.flows import signals as flow_signals
from nexus.flows import verifier as flow_verifier

logger = logging.getLogger("nexus.flows.runner")

# Guards a malformed/looping graph from consuming one sweep forever — the run
# simply gets picked back up on the next sweep from wherever it stopped.
_MAX_STEPS_PER_CLAIM = 25


class StepResult:
    def __init__(
        self, status: str, *, output: dict | None = None, error: str | None = None,
        next_node: str | None = None, park_at_current: bool = False,
    ):
        # 'success' | 'shadow' | 'blocked' | 'failed' | 'waiting'
        self.status = status
        self.output = output or {}
        self.error = error
        self.next_node = next_node   # explicit override (unused in V1; reserved)
        # 'waiting' only: park the run pointing at THIS node so it re-executes
        # on resume (a verifier defer = retry the send later), instead of the
        # default park-past-it (a wait node = continue beyond it).
        self.park_at_current = park_at_current


def run_sweep(conn, *, limit: int = 20) -> dict:
    """Resume fired timers, then claim + execute every runnable flow_run.
    Returns a summary dict for the manual-trigger endpoint / logs."""
    if not flow_policy.flows_enabled():
        return {"skipped": "flows.enabled is off", "claimed": 0}

    resumed = _resume_fired_timers(conn)
    claimed = _claim_running(conn, limit=limit)
    summary = {"resumed": resumed, "claimed": len(claimed),
               "success": 0, "waiting": 0, "failed": 0, "continuing": 0}
    for run in claimed:
        # Per-run SAVEPOINT isolation (the hooks.py discipline): one poisoned
        # run rolls back ITS OWN statements and fails alone — it can neither
        # abort the shared transaction for the runs after it nor kill the
        # sweep loop. The F1 review found both failure modes latent here.
        try:
            with conn.cursor() as cur:
                cur.execute("SAVEPOINT flows_run")
            outcome = _drive(conn, run)
            with conn.cursor() as cur:
                cur.execute("RELEASE SAVEPOINT flows_run")
        except Exception as exc:
            logger.exception("[runner] run %s crashed — isolating", run["id"])
            try:
                with conn.cursor() as cur:
                    cur.execute("ROLLBACK TO SAVEPOINT flows_run")
                    cur.execute("RELEASE SAVEPOINT flows_run")
                _fail_run(conn, run["id"], f"{type(exc).__name__}: {exc}")
            except Exception as e2:
                logger.warning("[runner] rollback/fail after crash also failed: %s", e2)
            flow_memory.record_failure(
                "run_crashed", flow_slug=run.get("flow_slug"),
                person_id=run.get("person_id"),
                reason=type(exc).__name__, detail=str(exc),
            )
            outcome = "failed"
        summary[outcome] = summary.get(outcome, 0) + 1
    return summary


# ── Claiming ──────────────────────────────────────────────────────────────────

def _claim_running(conn, *, limit: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fr.id, fr.flow_id, fr.person_id, fr.cursor_node, fr.context, "
            "       fd.slug, fd.live, fd.graph, fd.trigger "
            "FROM flow_runs fr JOIN flow_definitions fd ON fd.id = fr.flow_id "
            "WHERE fr.status = 'running' AND fd.status IN ('published', 'paused') "
            "ORDER BY fr.started_at ASC LIMIT %s "
            "FOR UPDATE OF fr SKIP LOCKED",
            (limit,),
        )
        rows = cur.fetchall()
    runs = []
    for r in rows:
        runs.append({
            "id": str(r[0]), "flow_id": str(r[1]), "person_id": str(r[2]),
            "cursor_node": r[3], "context": dict(r[4] or {}),
            "flow_slug": r[5], "flow_live": bool(r[6]), "graph": r[7],
            "trigger": r[8] or {},
        })
    return runs


def _resume_fired_timers(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_timers SET fired = TRUE "
            "WHERE fire_at <= NOW() AND fired = FALSE "
            "RETURNING flow_run_id"
        )
        run_ids = [str(r[0]) for r in cur.fetchall()]
    if not run_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_runs SET status = 'running' WHERE id = ANY(%s) AND status = 'waiting'",
            (run_ids,),
        )
    return len(run_ids)


# ── The graph walk ────────────────────────────────────────────────────────────

def _drive(conn, run: dict) -> str:
    graph = run["graph"] or {}
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])   # [{"from": id, "to": id, "when": "true"|"false"|None}]

    context = run["context"]
    if "signals" not in context:
        signals = flow_signals.signals_for(conn, run["person_id"])
        if signals:
            context["signals"] = signals
            context.setdefault("opportunity_id", signals.get("opportunity_id"))

    cursor = run["cursor_node"] or _entry_node_id(graph)
    last_condition_result: bool | None = None
    steps = 0

    while cursor and steps < _MAX_STEPS_PER_CLAIM:
        node = nodes.get(cursor)
        if node is None:
            _fail_run(conn, run["id"], f"unknown node id {cursor!r}")
            return "failed"
        steps += 1

        try:
            result = _execute_node(conn, run, node, context)
        except Exception as exc:
            logger.exception("[runner] node %s raised for run=%s", cursor, run["id"])
            _write_step(conn, run["id"], node, "failed", {}, f"{type(exc).__name__}: {exc}")
            _fail_run(conn, run["id"], f"{type(exc).__name__}: {exc}")
            return "failed"

        _write_step(conn, run["id"], node, result.status, result.output, result.error)

        if node.get("type") == "condition":
            last_condition_result = bool(result.output.get("result"))

        # Compute the NEXT node before branching on status — a park on
        # 'waiting' must resume PAST the wait node, never re-execute it (that
        # would insert a fresh flow_timers row and wait forever). The one
        # exception: park_at_current (a verifier defer) resumes AT the node,
        # because a deferred send must be re-attempted, not skipped.
        next_cursor = result.next_node or _next_node_id(edges, cursor, node.get("type"), last_condition_result)

        if result.status == "waiting":
            _park_waiting(conn, run["id"],
                          cursor if result.park_at_current else next_cursor, context)
            return "waiting"
        if result.status == "failed":
            _fail_run(conn, run["id"], result.error or "node failed")
            return "failed"

        cursor = next_cursor

    if cursor is None:
        _complete_run(conn, run["id"], context)
        return "success"

    # Ran out of step budget on a long/looping graph — save progress, stay
    # 'running' for the next sweep to continue from exactly here.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_runs SET cursor_node = %s, context = %s::jsonb WHERE id = %s",
            (cursor, json.dumps(context, default=str), run["id"]),
        )
    return "continuing"


def _entry_node_id(graph: dict) -> str | None:
    for n in graph.get("nodes", []):
        if n.get("type") == "trigger":
            return n["id"]
    nodes = graph.get("nodes", [])
    return nodes[0]["id"] if nodes else None


def _next_node_id(edges: list[dict], current: str, node_type: str | None, condition_result: bool | None) -> str | None:
    matches = [e for e in edges if e.get("from") == current]
    if node_type == "condition":
        want = "true" if condition_result else "false"
        for e in matches:
            if e.get("when") == want:
                return e.get("to")
        return None   # no edge for this branch — the run ends here, intentionally
    return matches[0].get("to") if matches else None


def _execute_node(conn, run: dict, node: dict, context: dict) -> StepResult:
    executor = _REGISTRY.get(node.get("type"))
    if executor is None:
        return StepResult("failed", error=f"unregistered node type {node.get('type')!r}")
    return executor(conn, run, node, context)


# ── Node executors ──────────────────────────────────────────────────────────────

def _exec_trigger(conn, run, node, context) -> StepResult:
    return StepResult("success")


def _exec_condition(conn, run, node, context) -> StepResult:
    predicate = node.get("predicate") or {}
    result = flow_predicates.evaluate(predicate, context.get("signals") or {})
    return StepResult("success", output={"result": result})


def _exec_wait(conn, run, node, context) -> StepResult:
    hours = node.get("hours")
    if not hours or hours <= 0:
        return StepResult("failed", error="wait node missing a positive 'hours'")
    fire_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO flow_timers (flow_run_id, fire_at) VALUES (%s, %s)",
            (run["id"], fire_at),
        )
    return StepResult("waiting", output={"fire_at": fire_at.isoformat()})


def _exec_advance_stage(conn, run, node, context) -> StepResult:
    opp_id = context.get("opportunity_id")
    to_stage = node.get("to_stage")
    if not opp_id or not to_stage:
        return StepResult("failed", error="action:advance_stage needs opportunity_id (context) + to_stage (node)")
    advanced = nexus_interactions.advance_stage(
        conn, opp_id, to_stage,
        reason=f"flow:{run['flow_slug']}", by=f"flow:{run['flow_slug']}",
    )
    return StepResult("success", output={"advanced": advanced, "to_stage": to_stage})


def _exec_add_note(conn, run, node, context) -> StepResult:
    nexus_interactions.log_interaction(
        conn, "note_added", "system", person_id=run["person_id"],
        payload={"by": f"flow:{run['flow_slug']}", "note": node.get("note", "")},
    )
    return StepResult("success")


def _exec_set_flag(conn, run, node, context) -> StepResult:
    nexus_interactions.log_interaction(
        conn, "flag_set", "system", person_id=run["person_id"],
        payload={"by": f"flow:{run['flow_slug']}", "flag": node.get("flag", "")},
    )
    return StepResult("success")


def _exec_send_message(conn, run, node, context) -> StepResult:
    body = node.get("body", "")
    if not run["flow_live"]:
        # Shadow mode runs the FULL Verifier Loop read-only (record=False so
        # an observed flow can't open a real circuit) and records the panel's
        # verdicts on the step — shadow review shows not just what would have
        # been sent, but whether it would have been vetoed and by whom.
        verification = flow_verifier.verify_send(
            conn, person_id=run["person_id"], text=body,
            source=f"flow:{run['flow_slug']}", flow_slug=run["flow_slug"],
            trigger=run.get("trigger"), record=False,
        )
        return StepResult("shadow", output={
            "would_send": body, "channel": "whatsapp",
            "verification": verification.as_dict(),
        })
    outcome = flow_policy.guarded_whatsapp_send(
        conn, person_id=run["person_id"], text=body,
        source=f"flow:{run['flow_slug']}", opportunity_id=context.get("opportunity_id"),
        flow_slug=run["flow_slug"], trigger=run.get("trigger"),
    )
    if not outcome.sent:
        output = {"reason": outcome.verdict.reason, "detail": outcome.verdict.detail}
        if outcome.verification is not None:
            output["verification"] = outcome.verification.as_dict()
        # A verifier DEFER parks the run pointing at this node and retries
        # after the panel's suggested backoff — reuses the durable-wait
        # machinery instead of dropping the send on the floor.
        if outcome.defer_hours:
            fire_at = (datetime.datetime.now(datetime.timezone.utc)
                       + datetime.timedelta(hours=outcome.defer_hours))
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO flow_timers (flow_run_id, fire_at) VALUES (%s, %s)",
                    (run["id"], fire_at),
                )
            output["retry_at"] = fire_at.isoformat()
            return StepResult("waiting", output=output, park_at_current=True)
        return StepResult("blocked", output=output)
    return StepResult("success", output={"provider_message_id": outcome.provider_message_id})


def _exec_notify_operator(conn, run, node, context) -> StepResult:
    text = node.get("body", "")
    if not run["flow_live"]:
        return StepResult("shadow", output={"would_notify": text})
    message_id = flow_policy.notify_operator(text)
    return StepResult("success" if message_id else "failed",
                      output={"message_id": message_id},
                      error=None if message_id else "Telegram send returned no message id")


_REGISTRY = {
    "trigger":                _exec_trigger,
    "condition":               _exec_condition,
    "wait":                    _exec_wait,
    "action:advance_stage":    _exec_advance_stage,
    "action:add_note":         _exec_add_note,
    "action:set_flag":         _exec_set_flag,
    "action:send_message":     _exec_send_message,
    "action:notify_operator":  _exec_notify_operator,
}


# ── Persistence ───────────────────────────────────────────────────────────────

def _write_step(conn, run_id: str, node: dict, status: str, output: dict, error: str | None) -> None:
    node_input = {k: v for k, v in node.items() if k not in ("id", "type")}
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO flow_run_steps "
            "(flow_run_id, node_id, node_type, status, input, output, error) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)",
            (run_id, node.get("id"), node.get("type"), status,
             json.dumps(node_input, default=str), json.dumps(output, default=str), error),
        )


def _park_waiting(conn, run_id: str, cursor_node: str, context: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_runs SET status = 'waiting', cursor_node = %s, context = %s::jsonb WHERE id = %s",
            (cursor_node, json.dumps(context, default=str), run_id),
        )


def _fail_run(conn, run_id: str, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_runs SET status = 'failed', completed_at = NOW() WHERE id = %s",
            (run_id,),
        )


def _complete_run(conn, run_id: str, context: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flow_runs SET status = 'success', context = %s::jsonb, completed_at = NOW() WHERE id = %s",
            (json.dumps(context, default=str), run_id),
        )
