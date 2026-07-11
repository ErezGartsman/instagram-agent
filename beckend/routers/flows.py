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
    prior phase already dispatched (SYSTEM_ELEVATION_PRD.md §B3). The cycle's
    cost lands in the flows memory efficiency ledger — the optimization
    record for tuning cadence and batch limits."""
    started = main.time.perf_counter()
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
    main.nexus_flows_memory.record_efficiency(
        "sweep_cycle",
        duration_ms=(main.time.perf_counter() - started) * 1000,
        counts={
            "events_dispatched": events_dispatched,
            "states_dispatched": states_dispatched,
            **{k: v for k, v in run_summary.items() if isinstance(v, int)},
        },
    )
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
                    "       fd.published_at, fd.graph, "
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
                # graph = {nodes:[{id,type,...}], edges:[{from,to,when?}]} — the
                # canvas renders this topology; F2 frontend needs it inline.
                "graph": r[10],
                "run_count": r[11], "last_run_at": r[12].isoformat() if r[12] else None,
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


# ── Authoring (F3, SYSTEM_ELEVATION_PRD.md §F3) ───────────────────────────────

def _actor(user: dict) -> str:
    return user.get("email") or user.get("sub") or "cockpit"


def _authoring_error(e) -> dict:
    """AuthoringError → a clean 4xx body the frontend surfaces verbatim."""
    raise main.HTTPException(status_code=422, detail=str(e))


@router.post("/api/cockpit/flows")
def create_flow(payload: dict = main.Body(...),
                user: dict = main.Depends(main.require_cockpit_user)):
    """Create a new DRAFT flow. Body: {name, description?, trigger, graph}."""
    try:
        with main.get_db_conn() as conn:
            flow_id = main.nexus_flows_authoring.create_draft(
                conn,
                name=payload.get("name", ""),
                description=payload.get("description"),
                trigger=payload.get("trigger") or {},
                graph=payload.get("graph") or {},
                created_by=_actor(user),
            )
            conn.commit()
        return {"status": "success", "id": flow_id}
    except main.nexus_flows_authoring.AuthoringError as e:
        _authoring_error(e)
    except Exception as e:
        main.logger.error(f"[flows] create failed: {e}")
        return {"status": "error", "detail": "Could not create the flow."}


@router.patch("/api/cockpit/flows/{flow_id}")
def update_flow(flow_id: str, payload: dict = main.Body(...),
                user: dict = main.Depends(main.require_cockpit_user)):
    """Patch a DRAFT flow. Any of {name, description, trigger, graph}."""
    try:
        with main.get_db_conn() as conn:
            main.nexus_flows_authoring.update_draft(
                conn, flow_id,
                name=payload.get("name"),
                description=payload.get("description"),
                trigger=payload.get("trigger"),
                graph=payload.get("graph"),
            )
            conn.commit()
        return {"status": "success"}
    except main.nexus_flows_authoring.AuthoringError as e:
        _authoring_error(e)
    except Exception as e:
        main.logger.error(f"[flows] update {flow_id} failed: {e}")
        return {"status": "error", "detail": "Could not update the flow."}


@router.post("/api/cockpit/flows/{flow_id}/fork")
def fork_flow(flow_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """Fork a published/paused flow into a new editable draft (version+1)."""
    try:
        with main.get_db_conn() as conn:
            new_id = main.nexus_flows_authoring.fork_draft(conn, flow_id, created_by=_actor(user))
            conn.commit()
        return {"status": "success", "id": new_id}
    except main.nexus_flows_authoring.AuthoringError as e:
        _authoring_error(e)
    except Exception as e:
        main.logger.error(f"[flows] fork {flow_id} failed: {e}")
        return {"status": "error", "detail": "Could not fork the flow."}


@router.post("/api/cockpit/flows/{flow_id}/simulate")
def simulate_flow_endpoint(flow_id: str, payload: dict = main.Body(default={}),
                           user: dict = main.Depends(main.require_cockpit_user)):
    """Run the 90-day time-travel simulation and return the impact report.
    Read-only — the publish endpoint re-runs it authoritatively. An optional
    {graph, trigger} in the body simulates UNSAVED edits without persisting."""
    days = int(payload.get("days") or main.nexus_flows_simulate.DEFAULT_WINDOW_DAYS)
    try:
        with main.get_db_conn() as conn:
            flow = main.nexus_flows_authoring.load_flow(conn, flow_id)
            if flow is None:
                raise main.HTTPException(status_code=404, detail="Flow not found.")
            trigger = payload.get("trigger") or flow["trigger"]
            graph = payload.get("graph") or flow["graph"]
            report = main.nexus_flows_simulate.simulate_flow(
                conn, trigger=trigger, graph=graph, days=days,
            )
        return {"status": "success", "report": report}
    except main.HTTPException:
        raise
    except Exception as e:
        main.logger.error(f"[flows] simulate {flow_id} failed: {e}")
        return {"status": "error", "detail": "Simulation failed — check server logs."}


@router.post("/api/cockpit/flows/{flow_id}/publish")
def publish_flow(flow_id: str, user: dict = main.Depends(main.require_cockpit_user)):
    """Publish a draft — GATED on a server-run simulation (authoritative; the
    UI dialog is advisory). Runs the sim, then publishes with it stored, all
    in one transaction."""
    try:
        with main.get_db_conn() as conn:
            flow = main.nexus_flows_authoring.load_flow(conn, flow_id)
            if flow is None:
                raise main.HTTPException(status_code=404, detail="Flow not found.")
            report = main.nexus_flows_simulate.simulate_flow(
                conn, trigger=flow["trigger"], graph=flow["graph"],
            )
            main.nexus_flows_authoring.publish(conn, flow_id, simulation=report)
            conn.commit()
        return {"status": "success", "report": report}
    except main.HTTPException:
        raise
    except main.nexus_flows_authoring.AuthoringError as e:
        _authoring_error(e)
    except Exception as e:
        main.logger.error(f"[flows] publish {flow_id} failed: {e}")
        return {"status": "error", "detail": "Could not publish the flow."}


@router.post("/api/cockpit/flows/{flow_id}/status")
def flow_status(flow_id: str, payload: dict = main.Body(...),
                user: dict = main.Depends(main.require_cockpit_user)):
    """Kill switches: {action: pause|resume|archive}."""
    action = payload.get("action")
    try:
        with main.get_db_conn() as conn:
            new_status = main.nexus_flows_authoring.set_status(conn, flow_id, action=action)
            conn.commit()
        return {"status": "success", "flow_status": new_status}
    except main.nexus_flows_authoring.AuthoringError as e:
        _authoring_error(e)
    except Exception as e:
        main.logger.error(f"[flows] status {flow_id} failed: {e}")
        return {"status": "error", "detail": "Could not change flow status."}


@router.post("/api/cockpit/flows/{flow_id}/live")
def flow_live(flow_id: str, payload: dict = main.Body(...),
              user: dict = main.Depends(main.require_cockpit_user)):
    """Flip a published flow out of shadow mode (or back). {live: bool}."""
    try:
        with main.get_db_conn() as conn:
            main.nexus_flows_authoring.set_live(conn, flow_id, live=bool(payload.get("live")))
            conn.commit()
        return {"status": "success"}
    except main.nexus_flows_authoring.AuthoringError as e:
        _authoring_error(e)
    except Exception as e:
        main.logger.error(f"[flows] live {flow_id} failed: {e}")
        return {"status": "error", "detail": "Could not change live state."}


@router.patch("/api/cockpit/flow-settings")
def flow_settings(payload: dict = main.Body(...),
                  user: dict = main.Depends(main.require_cockpit_user)):
    """Engine settings: {enabled?: bool, pressure_budget?: int} → app_config.
    Deliberately NOT under /flows/{id} — a static sub-path there would collide
    with the PATCH /flows/{flow_id} draft-update route."""
    updates = []
    if "enabled" in payload:
        updates.append(("flows.enabled", "true" if payload["enabled"] else "false",
                        "Flows engine master switch"))
    if "pressure_budget" in payload:
        try:
            budget = max(0, int(payload["pressure_budget"]))
        except (TypeError, ValueError):
            raise main.HTTPException(status_code=422, detail="pressure_budget must be a non-negative integer.")
        updates.append(("flows.pressure_budget", str(budget),
                        "Max automated messages per person per 7 days"))
    try:
        with main.get_db_conn() as conn:
            with conn.cursor() as cur:
                for key, value, desc in updates:
                    cur.execute(
                        "INSERT INTO app_config (key, value, description) VALUES (%s, %s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                        (key, value, desc),
                    )
            conn.commit()
        return {"status": "success",
                "enabled": main.nexus_flows_policy.flows_enabled(),
                "pressure_budget": main.nexus_flows_policy.pressure_budget()}
    except main.HTTPException:
        raise
    except Exception as e:
        main.logger.error(f"[flows] settings update failed: {e}")
        return {"status": "error", "detail": "Could not update settings."}


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
