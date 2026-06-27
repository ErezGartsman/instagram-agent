"""
scheduler — APScheduler cron for the Nexus autonomous agent sweep.

Runs every 6 hours and finds all 'engaged' leads that have been sitting
in that stage for at least MIN_ENGAGED_HOURS without a pending/running
qualification agent run, then fires run_agent for each.

⚠️  Vercel note: Vercel serverless functions are stateless and short-lived;
APScheduler's in-process BackgroundScheduler will not persist across cold
starts. The cron sweep is therefore only reliable in long-running server
deployments (local dev, a VPS, a container). The event-driven trigger in
`POST /api/cockpit/queue/{id}/action` is the primary production path.
This cron is the safety net for leads that were never touched via the
action loop (e.g. leads that arrived while Erez was away for a day).
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from nexus import db as nexus_db
from nexus.agents.base import run_agent
from nexus.agents.qualification import qualification_agent

logger = logging.getLogger("nexus.scheduler")

# Minimum time a lead must have been in 'engaged' before the sweep picks it up.
# Short enough to catch neglected leads; long enough to give Erez a window to
# manually act first (event-driven path) without the agent racing him.
_MIN_ENGAGED_HOURS = 1

_scheduler = BackgroundScheduler(
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    timezone="Asia/Jerusalem",
)


def _on_job_event(event) -> None:
    """Scheduler event listener — logs errors without crashing the scheduler."""
    if event.exception:
        logger.error(
            "[scheduler] job %s raised: %s", event.job_id, event.exception
        )
    else:
        logger.debug("[scheduler] job %s executed successfully", event.job_id)


def _refresh_funnel_metrics() -> None:
    """
    Refresh the funnel_metrics materialized view. Runs nightly at 03:00 Asia/Jerusalem.
    Cheap on a small dataset; safe to re-run any time.
    """
    logger.info("[scheduler] refreshing funnel_metrics")
    try:
        with nexus_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY funnel_metrics")
            conn.commit()
        logger.info("[scheduler] funnel_metrics refreshed")
    except Exception as exc:
        logger.error("[scheduler] funnel_metrics refresh failed: %s", exc)


def _sweep_qualification() -> None:
    """
    Find all open 'engaged' opportunities older than MIN_ENGAGED_HOURS that have
    no pending/running qualification agent run, then fire the qualification agent
    for each as a standalone run (run_agent owns its own connection + commit).

    Individual lead failures are caught and logged — one bad lead never aborts
    the sweep of the remaining leads.
    """
    logger.info("[scheduler] qualification sweep starting")
    try:
        with nexus_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT o.person_id
                    FROM opportunities o
                    WHERE o.stage = 'engaged'
                      AND o.closed_at IS NULL
                      AND o.stage_entered_at <= NOW() - (%s * interval '1 hour')
                      AND NOT EXISTS (
                          SELECT 1 FROM agent_runs ar
                          WHERE ar.person_id = o.person_id
                            AND ar.agent_type = 'qualification'
                            AND ar.status IN ('pending', 'running')
                      )
                    ORDER BY o.stage_entered_at ASC
                    """,
                    (_MIN_ENGAGED_HOURS,),
                )
                person_ids = [str(row[0]) for row in cur.fetchall()]
    except Exception as exc:
        logger.error("[scheduler] sweep DB query failed: %s", exc)
        return

    logger.info("[scheduler] sweep found %d leads to evaluate", len(person_ids))
    for person_id in person_ids:
        try:
            run_agent(
                agent_type="qualification",
                person_id=person_id,
                triggered_by="cron",
                agent_fn=qualification_agent,
                input_snapshot={"sweep_min_hours": _MIN_ENGAGED_HOURS},
            )
        except Exception as exc:
            logger.error(
                "[scheduler] run_agent failed for person=%s: %s", person_id, exc
            )


def start() -> None:
    """Start the scheduler. Called from the FastAPI lifespan startup hook."""
    _scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
    _scheduler.add_job(
        _sweep_qualification,
        trigger="interval",
        hours=6,
        id="qualification_sweep",
        replace_existing=True,
    )
    _scheduler.add_job(
        _refresh_funnel_metrics,
        trigger="cron",
        hour=3,
        minute=0,
        id="funnel_metrics_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("[scheduler] started — qualification sweep every 6h, funnel_metrics refresh nightly at 03:00")


def stop() -> None:
    """Shut down the scheduler gracefully. Called from the FastAPI lifespan shutdown hook."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] stopped")
