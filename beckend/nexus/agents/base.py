"""
nexus.agents.base — the universal agent runner.

Every agent (qualification, follow_up, re_engage, ...) runs through
run_agent(). This wrapper provides:

  1. Idempotency — skips silently if a pending/running run already exists
     for this (person_id, agent_type) pair. Prevents the 6-hour cron sweep
     and the event-driven trigger from creating duplicate runs.

  2. Lifecycle logging — opens an agent_runs row at 'running' and commits it
     immediately so the cockpit UI can observe agent activity in real time via
     Supabase Realtime. Closes the row as 'success', 'skipped', or 'failed'
     after the agent function returns.

  3. Action persistence — every AgentAction the agent reports is persisted to
     agent_actions, giving the cockpit's Activity Feed its granular log.

  4. Own connection + commit — run_agent acquires its own pooled DB connection
     because it is always called from a FastAPI BackgroundTask (the request
     that triggered it has already returned). It follows the same two-phase
     commit pattern used by nexus.interactions.track: one commit to make the
     'running' row visible, one final commit for all agent work + close.

  5. Never raises — a background agent failure must never crash a webhook turn
     or leave the DB in an inconsistent state. All exceptions are caught,
     logged, and persisted as status='failed'.

Usage (from main.py or any FastAPI route):

    from fastapi import BackgroundTasks
    from nexus.agents.base import run_agent
    from nexus.agents.qualification import qualification_agent

    @app.post("/api/cockpit/queue/{opp_id}/action")
    async def action(opp_id: str, background_tasks: BackgroundTasks, ...):
        # ... process the action ...
        background_tasks.add_task(
            run_agent,
            agent_type="qualification",
            person_id=person_id,
            triggered_by="stage_change",
            agent_fn=qualification_agent,
            input_snapshot={"stage": new_stage, "opportunity_id": opp_id},
        )
        return {"ok": True}
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from nexus import db

logger = logging.getLogger("nexus.agents")


# ── Public data contracts ──────────────────────────────────────────────────────

@dataclass
class AgentAction:
    """
    One discrete step taken inside a single agent run.

    action_type values (extend as needed):
        'whatsapp_sent'   — outbound WA message dispatched
        'stage_advanced'  — opportunity moved to a new stage
        'flag_set'        — a flag/label applied to the person/opportunity
        'note_added'      — a note written to interactions log
        'info_requested'  — an info_requests row inserted
        'skipped'         — agent decided to do nothing (with documented reason)
    """
    action_type: str
    payload: dict = field(default_factory=dict)  # what was sent / changed
    result: dict = field(default_factory=dict)   # outcome of the action


@dataclass
class AgentResult:
    """
    The complete outcome of one agent run — returned by every agent_fn.

    status:
        'success'  — agent ran and took at least one meaningful action
        'skipped'  — agent ran, evaluated, and correctly chose to do nothing
                     (e.g. info already complete, request already sent).
                     Skipped runs are NOT failures — they are expected steady-state.
        'failed'   — an unexpected exception interrupted the agent
    """
    status: str                                  # 'success' | 'skipped' | 'failed'
    actions: list[AgentAction] = field(default_factory=list)
    output: dict = field(default_factory=dict)   # freeform summary stored on the run row
    error: str | None = None                     # populated only when status='failed'


# Type alias — the signature every agent function must satisfy.
# conn  : open psycopg2 connection (commit-free — run_agent owns commits)
# person_id : UUID string of the person being evaluated
# run_id    : UUID string of the current agent_runs row (for self-referential actions)
AgentFn = Callable[[Any, str, str], AgentResult]


# ── Public entry point ─────────────────────────────────────────────────────────

def run_agent(
    *,
    agent_type: str,
    person_id: str,
    triggered_by: str,
    agent_fn: AgentFn,
    input_snapshot: dict | None = None,
) -> None:
    """
    Universal agent runner. Always call this from a FastAPI BackgroundTask —
    never await it from a request path (it acquires its own DB connection).

    Parameters
    ----------
    agent_type      : stable identifier — e.g. 'qualification', 'follow_up'.
                      Used as the idempotency key alongside person_id.
    person_id       : UUID string of the Person being evaluated.
    triggered_by    : audit label — 'stage_change' | 'cron' | 'manual'.
    agent_fn        : the actual agent logic (see nexus/agents/qualification.py).
    input_snapshot  : optional dict snapshot of state at trigger time (stored on
                      the run row; useful for debugging without replaying history).
    """
    try:
        with db.get_conn() as conn:
            _execute(
                conn=conn,
                agent_type=agent_type,
                person_id=person_id,
                triggered_by=triggered_by,
                agent_fn=agent_fn,
                input_snapshot=input_snapshot or {},
            )
            # Final commit: agent_fn's DB work + agent_actions + run status close.
            # (The intermediate commit for the 'running' row happened inside _execute.)
            conn.commit()
    except Exception as exc:
        # Outer guard: catches pool exhaustion, connection errors, etc.
        logger.error(
            "[agents] run_agent outer-guard: agent=%r person=%s error=%s: %s",
            agent_type, person_id, type(exc).__name__, exc,
        )


# ── Private implementation ─────────────────────────────────────────────────────

def _execute(
    conn,
    agent_type: str,
    person_id: str,
    triggered_by: str,
    agent_fn: AgentFn,
    input_snapshot: dict,
) -> None:
    """
    Core execution: idempotency check → open run row → call agent → persist
    actions → close run row. Two explicit commits:
      commit-1 (after opening the run row): makes 'running' visible in real time.
      commit-2 (in run_agent, after _execute returns): persists all agent work.
    """
    run_id = str(uuid.uuid4())

    # ── 1. Idempotency guard ──────────────────────────────────────────────────
    # If any run for this (person, agent_type) is already pending or running,
    # bail out silently. The cron sweep and the event trigger can race; exactly
    # one of them wins.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM agent_runs "
            "WHERE person_id = %s AND agent_type = %s "
            "  AND status IN ('pending', 'running') "
            "LIMIT 1",
            (person_id, agent_type),
        )
        if cur.fetchone() is not None:
            logger.info(
                "[agents] %r already in flight for person=%s — skipping duplicate trigger",
                agent_type, person_id,
            )
            return

    # ── 2. Open the run row at 'running' ──────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_runs "
            "  (id, person_id, agent_type, status, triggered_by, input) "
            "VALUES (%s, %s, %s, 'running', %s, %s::jsonb)",
            (
                run_id,
                person_id,
                agent_type,
                triggered_by,
                json.dumps(input_snapshot, default=str),
            ),
        )

    # Commit-1: the 'running' row is now durable and visible to Supabase Realtime.
    # The cockpit AgentPip component will light up immediately.
    conn.commit()
    logger.info(
        "[agents] %r started for person=%s run=%s triggered_by=%s",
        agent_type, person_id, run_id, triggered_by,
    )

    # ── 3. Call the agent function ────────────────────────────────────────────
    # agent_fn is commit-free — it uses the same conn and accumulates DB work
    # that will be committed together in commit-2.
    result: AgentResult
    try:
        result = agent_fn(conn, person_id, run_id)
    except Exception as exc:
        logger.exception(
            "[agents] %r raised for person=%s run=%s",
            agent_type, person_id, run_id,
        )
        result = AgentResult(
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )

    # ── 4. Persist agent_actions ──────────────────────────────────────────────
    if result.actions:
        with conn.cursor() as cur:
            for action in result.actions:
                cur.execute(
                    "INSERT INTO agent_actions "
                    "  (agent_run_id, action_type, payload, result) "
                    "VALUES (%s, %s, %s::jsonb, %s::jsonb)",
                    (
                        run_id,
                        action.action_type,
                        json.dumps(action.payload, default=str),
                        json.dumps(action.result, default=str),
                    ),
                )

    # ── 5. Close the run row ──────────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_runs "
            "SET status = %s, output = %s::jsonb, error = %s, completed_at = NOW() "
            "WHERE id = %s",
            (
                result.status,
                json.dumps(result.output, default=str),
                result.error,
                run_id,
            ),
        )
    # Commit-2 happens in the caller (run_agent) after _execute returns.

    logger.info(
        "[agents] %r finished person=%s run=%s status=%s actions=%d",
        agent_type, person_id, run_id, result.status, len(result.actions),
    )
