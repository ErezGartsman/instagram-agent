"""
nexus.agents.qualification — the QualificationAgent.

Evaluates one 'engaged' lead and takes one of three paths:

  1. ADVANCE   — goal AND tension are already present in person_profile.attributes
                 → advance the opportunity to 'qualified' and log the transition.

  2. REQUEST   — goal or tension is missing AND no info request was sent in the
                 last 48 hours → compose a WhatsApp message, send it, persist to
                 outbound_messages + info_requests.

  3. SKIP      — lead is not in 'engaged' stage, info request was sent recently,
                 or there is no WhatsApp number to send to. Logged as 'skipped'
                 (not a failure — expected steady state).

Conforms to the AgentFn interface in nexus.agents.base.
All DB work is commit-free; run_agent owns the transaction boundaries.
"""

from __future__ import annotations

import logging

from nexus import interactions as nexus_interactions
from nexus.agents.base import AgentAction, AgentResult
from nexus.flows import policy as flow_policy

logger = logging.getLogger("nexus.agents.qualification")

# Only leads that have been in 'engaged' for at least this many hours are swept
# by the cron. The event-driven trigger (from the action endpoint) always fires
# regardless of age — so a brand-new lead evaluated right after its first action
# is caught immediately.
_MIN_ENGAGED_HOURS = 1

# How long to wait before sending another info request to the same person.
_INFO_REQUEST_COOLOFF_HOURS = 48


# ── Main agent function ────────────────────────────────────────────────────────

def qualification_agent(conn, person_id: str, run_id: str) -> AgentResult:
    """
    QualificationAgent — the AgentFn called by run_agent.

    conn      : open psycopg2 connection (commit-free)
    person_id : UUID string of the person being evaluated
    run_id    : UUID string of the current agent_runs row (for self-referential
                action payloads — not written to here, logged by run_agent)
    """
    # ── 1. Load Person-360 and the open opportunity ───────────────────────────
    person = _load_person(conn, person_id)
    if person is None:
        logger.info("[qualification] person %s not found — skipping", person_id)
        return AgentResult(status="skipped", output={"reason": "person_not_found"})

    opp = _load_open_opportunity(conn, person_id)
    if opp is None:
        logger.info("[qualification] no open opportunity for %s — skipping", person_id)
        return AgentResult(status="skipped", output={"reason": "no_open_opportunity"})

    opportunity_id, stage, _source_channel = opp

    # ── 2. Guard: only act on 'engaged' leads ─────────────────────────────────
    if stage != "engaged":
        logger.info(
            "[qualification] person %s is in stage=%s — skipping", person_id, stage
        )
        return AgentResult(
            status="skipped",
            output={"reason": "not_in_engaged_stage", "stage": stage},
        )

    # ── 3. Evaluate completeness ──────────────────────────────────────────────
    goal    = person.get("goal")
    tension = person.get("tension")
    missing = [f for f, v in [("goal", goal), ("tension", tension)] if not v]

    if not missing:
        # ── PATH A: ADVANCE ───────────────────────────────────────────────────
        advanced = nexus_interactions.advance_stage(
            conn, opportunity_id, "qualified",
            reason="goal and tension complete — auto-qualified by agent",
            by="agent:qualification",
        )
        if not advanced:
            return AgentResult(
                status="skipped",
                output={"reason": "advance_stage_no_op", "stage": stage},
            )
        logger.info("[qualification] advanced %s → qualified", person_id)
        return AgentResult(
            status="success",
            actions=[
                AgentAction(
                    action_type="stage_advanced",
                    payload={"from": "engaged", "to": "qualified",
                             "opportunity_id": opportunity_id},
                    result={"advanced": True},
                )
            ],
            output={"reason": "goal_and_tension_complete", "new_stage": "qualified"},
        )

    # ── PATH B or C (info missing) ────────────────────────────────────────────

    # ── 4. 48-hour dedup guard ────────────────────────────────────────────────
    if _has_recent_info_request(conn, person_id, hours=_INFO_REQUEST_COOLOFF_HOURS):
        logger.info(
            "[qualification] info request already sent recently to %s — skipping",
            person_id,
        )
        return AgentResult(
            status="skipped",
            output={
                "reason": "info_request_sent_recently",
                "missing": missing,
                "cooloff_hours": _INFO_REQUEST_COOLOFF_HOURS,
            },
        )

    # ── 5. Compose and send via the Policy Gate ───────────────────────────────
    # guarded_whatsapp_send (SYSTEM_ELEVATION_PRD.md §B5/F1) unifies this
    # agent's sends with Flows' — crisis/pressure-budget/quiet-hours/channel-
    # window checks now apply here for the first time, and the recipient
    # lookup + outbound_messages persist + 'contacted' log all live there so
    # they can't drift between this agent and a flow's own send node.
    name       = person.get("name", "")
    first_name = name.split()[0] if name else ""
    message    = _compose_info_request(first_name, missing)

    outcome = flow_policy.guarded_whatsapp_send(
        conn, person_id=person_id, text=message, source="agent:qualification",
        opportunity_id=opportunity_id,
    )
    if not outcome.sent:
        is_failure = outcome.verdict.reason == "send_failed"
        logger.log(
            logging.WARNING if is_failure else logging.INFO,
            "[qualification] send %s for %s: %s (%s)",
            "failed" if is_failure else "blocked", person_id,
            outcome.verdict.reason, outcome.verdict.detail,
        )
        return AgentResult(
            status="failed" if is_failure else "skipped",
            output={"reason": outcome.verdict.reason, "detail": outcome.verdict.detail, "missing": missing},
            error="WhatsApp send returned no response — channel or token issue" if is_failure else None,
        )

    message_id = outcome.provider_message_id

    # ── 6. Insert info_requests row (idempotency table for future sweeps) ────
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO info_requests "
            "  (person_id, agent_run_id, fields_missing, message_sent) "
            "VALUES (%s, %s, %s, %s)",
            (person_id, run_id, missing, message),
        )

    logger.info(
        "[qualification] info request sent to %s (missing=%s)", person_id, missing
    )
    return AgentResult(
        status="success",
        actions=[
            AgentAction(
                action_type="whatsapp_sent",
                payload={
                    "missing_fields": missing,
                    "message_id": message_id,
                },
                result={"sent": True},
            ),
            AgentAction(
                action_type="info_requested",
                payload={"fields_missing": missing},
                result={"info_request_inserted": True},
            ),
        ],
        output={"reason": "info_requested", "missing": missing},
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _load_person(conn, person_id: str) -> dict | None:
    """
    Load the minimal Person-360 needed for qualification: name, goal, tension.
    Mirrors the _db_person360 shape in main.py (attrs from person_profile).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.display_name, p.wa_ref_code,
                   pp.attributes,
                   ss.emotional_state
            FROM person p
            LEFT JOIN person_profile pp ON pp.person_id = p.id
            LEFT JOIN LATERAL (
                SELECT emotional_state
                FROM session_summaries
                WHERE person_id = p.id
                ORDER BY created_at DESC LIMIT 1
            ) ss ON TRUE
            WHERE p.id = %s
            """,
            (person_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    display_name, wa_ref, attributes, emotional_state = row
    attrs = attributes if isinstance(attributes, dict) else {}
    name = display_name or (f"Lead {wa_ref}" if wa_ref else "Lead")
    return {
        "name": name,
        "goal": attrs.get("goal"),
        # Prefer the stored tension; fall back to the last session emotional state.
        "tension": attrs.get("tension") or emotional_state,
    }


def _load_open_opportunity(conn, person_id: str) -> tuple[str, str, str] | None:
    """Return (opportunity_id, stage, source_channel) for the open opportunity, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, stage, source_channel "
            "FROM opportunities "
            "WHERE person_id = %s AND closed_at IS NULL "
            "LIMIT 1",
            (person_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return str(row[0]), row[1], row[2]


def _has_recent_info_request(conn, person_id: str, *, hours: int) -> bool:
    """True when an unfulfilled info request was sent within the last `hours` hours."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM info_requests "
            "WHERE person_id = %s "
            "  AND fulfilled = FALSE "
            "  AND sent_at >= NOW() - (%s * interval '1 hour') "
            "LIMIT 1",
            (person_id, hours),
        )
        return cur.fetchone() is not None


def _compose_info_request(first_name: str, missing: list[str]) -> str:
    """
    Compose the WhatsApp message requesting missing profile fields.
    Professional, intake-focused tone — not therapeutic.
    Hebrew (primary channel language).
    """
    greeting = f"שלום {first_name}," if first_name else "שלום,"

    lines = [
        greeting,
        "",
        "כדי שנוכל להכין את הפגישה הראשונה שלנו בצורה הטובה ביותר, אשמח לדעת עוד קצת:",
        "",
    ]

    if "goal" in missing and "tension" in missing:
        lines += [
            "• מה המטרה העיקרית שאתה רוצה להשיג?",
            "• מה האתגר המרכזי שאתה מתמודד איתו כרגע?",
        ]
    elif "goal" in missing:
        lines.append("• מה המטרה העיקרית שאתה רוצה להשיג?")
    else:
        lines.append("• מה האתגר המרכזי שאתה מתמודד איתו כרגע?")

    lines += ["", "תודה רבה 🙏"]
    return "\n".join(lines)
