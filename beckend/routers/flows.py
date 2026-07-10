"""
routers.flows — the Flows engine API surface (F1, SYSTEM_ELEVATION_PRD.md §B).

The engine itself lives in nexus/flows/ (dispatcher, runner, policy,
predicates, signals); this module is a thin HTTP layer over it, per the E0
rule that new features never land inside main.py.

Two sweep triggers, both idempotent (safe to call repeatedly / concurrently):
  POST /api/cockpit/flows/sweep   — cockpit-auth-gated manual trigger, for
                                     verification and until a cron cadence is
                                     wired (a deliberate, separate infra
                                     decision — see the PR description).
  POST /api/cron/flows-sweep      — CRON_SECRET-gated, mirrors main.py's
                                     cron_crm_sync/cron_memory_sweep pattern
                                     exactly, ready to add to vercel.json
                                     once that cadence decision is made.
"""
from fastapi import APIRouter, Header
from typing import Optional

import main

router = APIRouter()


def _run_sweep_cycle() -> dict:
    """Dispatch events, dispatch states, then run the executor — each phase
    its own commit, so a failure in a later phase never rolls back runs a
    prior phase already dispatched (SYSTEM_ELEVATION_PRD.md §B3)."""
    events_dispatched = 0
    states_dispatched = 0
    with main.get_db_conn() as conn:
        events_dispatched = main.nexus_flows_dispatcher.dispatch_events(conn)
        conn.commit()
    with main.get_db_conn() as conn:
        states_dispatched = main.nexus_flows_dispatcher.dispatch_states(conn)
        conn.commit()
    with main.get_db_conn() as conn:
        run_summary = main.nexus_flows_runner.run_sweep(conn)
        conn.commit()
    return {
        "events_dispatched": events_dispatched,
        "states_dispatched": states_dispatched,
        "run": run_summary,
    }


@router.get("/api/cockpit/flows")
def list_flows(user: dict = main.Depends(main.require_cockpit_user)):
    """Flow definitions — the published/paused/draft/archived list, with a
    per-flow run-count summary. F2 builds the canvas on top of this."""
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT fd.id, fd.slug, fd.version, fd.status, fd.live, "
                    "       fd.name, fd.description, fd.trigger, fd.created_at, "
                    "       fd.published_at, "
                    "       (SELECT COUNT(*) FROM flow_runs fr WHERE fr.flow_id = fd.id) AS run_count, "
                    "       (SELECT MAX(fr.started_at) FROM flow_runs fr WHERE fr.flow_id = fd.id) AS last_run_at "
                    "FROM flow_definitions fd "
                    "ORDER BY fd.slug, fd.version DESC"
                )
                rows = cur.fetchall()
        flows = [
            {
                "id": str(r[0]), "slug": r[1], "version": r[2], "status": r[3],
                "live": r[4], "name": r[5], "description": r[6], "trigger": r[7],
                "created_at": r[8].isoformat() if r[8] else None,
                "published_at": r[9].isoformat() if r[9] else None,
                "run_count": r[10], "last_run_at": r[11].isoformat() if r[11] else None,
            }
            for r in rows
        ]
        return {
            "status": "success",
            "enabled": main.nexus_flows_policy.flows_enabled(),
            "flows": flows,
        }
    except Exception as e:
        main.logger.error(f"[flows] list failed: {e}")
        return {"status": "error", "detail": "Could not load flows.", "enabled": False, "flows": []}


@router.get("/api/cockpit/flows/{flow_id}/runs")
def list_flow_runs(flow_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """Recent runs for one flow, newest first — the F2 canvas's run-history
    panel; useful right now to verify shadow-mode behavior end to end."""
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT fr.id, fr.person_id, p.display_name, fr.status, "
                    "       fr.cursor_node, fr.started_at, fr.completed_at "
                    "FROM flow_runs fr JOIN person p ON p.id = fr.person_id "
                    "WHERE fr.flow_id = %s "
                    "ORDER BY fr.started_at DESC LIMIT 50",
                    (flow_id,),
                )
                runs = cur.fetchall()
                run_ids = [str(r[0]) for r in runs]
                steps_by_run: dict[str, list] = {rid: [] for rid in run_ids}
                if run_ids:
                    cur.execute(
                        "SELECT flow_run_id, node_id, node_type, status, output, error, at "
                        "FROM flow_run_steps WHERE flow_run_id = ANY(%s) ORDER BY at ASC",
                        (run_ids,),
                    )
                    for run_id, node_id, node_type, status, output, error, at in cur.fetchall():
                        steps_by_run[str(run_id)].append({
                            "node_id": node_id, "node_type": node_type, "status": status,
                            "output": output, "error": error, "at": at.isoformat() if at else None,
                        })
        return {
            "status": "success",
            "runs": [
                {
                    "id": str(r[0]), "person_id": str(r[1]), "person_name": r[2],
                    "status": r[3], "cursor_node": r[4],
                    "started_at": r[5].isoformat() if r[5] else None,
                    "completed_at": r[6].isoformat() if r[6] else None,
                    "steps": steps_by_run[str(r[0])],
                }
                for r in runs
            ],
        }
    except Exception as e:
        main.logger.error(f"[flows] list_runs failed for {flow_id}: {e}")
        return {"status": "error", "detail": "Could not load runs.", "runs": []}


@router.post("/api/cockpit/flows/sweep")
def trigger_sweep(user: dict = main.Depends(main.require_cockpit_user)):
    """Manual trigger — dispatch + run once, synchronously, for verification.
    Idempotent like every sweep; safe to click repeatedly."""
    try:
        return {"status": "success", **_run_sweep_cycle()}
    except Exception as e:
        main.logger.error(f"[flows] manual sweep failed: {e}")
        return {"status": "error", "detail": "Sweep failed — check server logs."}


@router.post("/api/cron/flows-sweep")
def cron_flows_sweep(
    authorization: Optional[str] = Header(default=None),
    x_cron_secret: Optional[str] = Header(default=None),
):
    """Cron-triggered sweep — same CRON_SECRET fail-closed guard as
    main.cron_crm_sync / main.cron_memory_sweep. NOT yet wired into
    vercel.json's `crons` array (a deliberate, separate infra decision —
    see the PR description); reachable today only with the secret."""
    if main.settings.cron_secret:
        bearer = authorization or ""
        if bearer.startswith("Bearer "):
            bearer = bearer[len("Bearer "):].strip()
        if not (main._secret_eq(bearer, main.settings.cron_secret)
                or main._secret_eq(x_cron_secret, main.settings.cron_secret)):
            raise main.HTTPException(status_code=401, detail="Invalid cron secret.")
    elif main.os.environ.get("VERCEL"):
        main.logger.error("[cron] CRON_SECRET is not set — flows-sweep disabled in production.")
        raise main.HTTPException(status_code=503, detail="Cron endpoint not configured.")

    try:
        return {"status": "success", **_run_sweep_cycle()}
    except Exception as e:
        main.logger.error(f"[flows] cron sweep failed: {e}")
        return {"status": "error", "detail": "Sweep failed — check server logs."}
