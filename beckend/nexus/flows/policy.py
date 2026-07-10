"""
nexus.flows.policy — the Policy Gate (SYSTEM_ELEVATION_PRD.md §B5): the ONE
choke point every automated outbound WhatsApp message passes through, whoever
originated it — a flow, the qualification agent, or a future cron. Unifies
the three previously-uncoordinated automation systems instead of Flows
becoming a fourth (PRD Blind Spot #1).

Order of checks — first veto wins:
  1. Crisis    — a recent inbound crisis signal from this person blocks ALL
                 automation on them, unconditionally. Absolute, upstream.
  2. Intake    — structural, not a runtime check: this module never composes
                 or generates text. Every caller passes pre-approved
                 operator-voice copy (a flow template, or the qualification
                 agent's fixed intake-focused message) — there is no code
                 path here that could produce bot-persona counseling text.
  3. Pressure  — max N automated messages / person / rolling 7 days, counted
                 ACROSS every system (outbound_messages.sent_by prefix), so
                 three polite senders can't still harass one person (PRD
                 Blind Spot #2 — per-source limits don't compose; a per-person
                 budget does).
  4. Quiet     — no automated sends 21:00-09:00 Asia/Jerusalem.
  5. Channel   — the WhatsApp/Instagram 24h customer-service window.

Kill switches (flows.enabled, per-flow `live`) are NOT checked here — those
gate whether the FLOWS ENGINE runs at all (checked at claim time by
nexus.flows.runner, "mid-flight runs park immediately" per the PRD) and
whether a specific flow may perform real external actions. This module's job
is per-send safety, applied uniformly regardless of who's asking.

Bridged the same way nexus.db / nexus.whatsapp are — nexus.flows cannot
import main (circular import). main.py calls configure() once at startup.
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo

from nexus import identity as nexus_identity
from nexus import interactions as nexus_interactions
from nexus import whatsapp as nexus_whatsapp
from nexus.flows import memory as flow_memory
from nexus.flows import verifier as flow_verifier

logger = logging.getLogger("nexus.flows.policy")

_IL_TZ = ZoneInfo("Asia/Jerusalem")
_QUIET_START_HOUR = 21   # 21:00 local — automation stands down
_QUIET_END_HOUR = 9      # 09:00 local — automation resumes
_DEFAULT_PRESSURE_BUDGET = 2
_PRESSURE_WINDOW_DAYS = 7
# Any outbound_messages.sent_by starting with one of these is "automated" for
# pressure-budget purposes. Manual cockpit sends use a bare operator email
# (migration v1_007's comment: "operator email (cockpit JWT)") — emails never
# contain ':', so this prefix check cannot collide with a manual send.
_AUTOMATED_SENT_BY_PREFIXES = ("agent:", "flow:", "cron:")


# ── The configure() bridge ─────────────────────────────────────────────────────

_is_crisis_fn: Callable[[str], bool] | None = None
_channel_eligibility_fn: Callable[..., dict] | None = None
_get_config_fn: Callable[[str], str] | None = None
_notify_operator_fn: Callable[[str], str | None] | None = None


def configure(
    *,
    is_crisis_fn: Callable[[str], bool],
    channel_eligibility_fn: Callable[..., dict],
    get_config_fn: Callable[[str], str],
    notify_operator_fn: Callable[[str], str | None],
) -> None:
    """Install main.py's crisis detector, channel-window checker, app_config
    reader, and operator-Telegram sender. Called once at main.py import time,
    mirroring nexus.db.configure / nexus.whatsapp.configure."""
    global _is_crisis_fn, _channel_eligibility_fn, _get_config_fn, _notify_operator_fn
    _is_crisis_fn = is_crisis_fn
    _channel_eligibility_fn = channel_eligibility_fn
    _get_config_fn = get_config_fn
    _notify_operator_fn = notify_operator_fn


# ── Verdict ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    reason: str | None = None   # blocking reason code; None when allowed
    detail: str = ""


@dataclass
class SendOutcome:
    sent: bool
    verdict: PolicyVerdict
    provider_message_id: str | None = None
    # The Verifier Loop's full panel record (nexus/flows/verifier.py) — None
    # when the Policy Gate itself vetoed before the panel convened.
    verification: "flow_verifier.SendVerification | None" = None
    # Set when the panel said "defer": callers that can park-and-retry (the
    # flow runner) should retry after this many hours; callers that can't
    # (the qualification agent) treat it as a skip.
    defer_hours: float | None = None


# ── Pure sub-checks (no DB) ─────────────────────────────────────────────────────

def quiet_hours_block(now: datetime.datetime | None = None) -> bool:
    """True when `now` (default: this moment) falls inside the automation
    quiet window, 21:00-09:00 Asia/Jerusalem local time — the leads this
    business reaches are Hebrew-speaking locals."""
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    local_hour = moment.astimezone(_IL_TZ).hour
    return local_hour >= _QUIET_START_HOUR or local_hour < _QUIET_END_HOUR


def _flag_on(key: str) -> bool:
    if _get_config_fn is None:
        return False
    return (_get_config_fn(key) or "").strip().lower() == "true"


def flows_enabled() -> bool:
    """The engine-level kill switch — checked by the runner AT CLAIM TIME
    (PRD §B5.6: "mid-flight runs park immediately"), not by evaluate_send.
    Whether a specific flow may perform real external actions is a separate,
    per-flow concern (flow_definitions.live)."""
    return _flag_on("flows.enabled")


def pressure_budget() -> int:
    """The configured per-person/7-day automated-message ceiling. Never
    raises; falls back to the documented default (2) on missing/malformed
    config, matching _get_config's own never-raises discipline."""
    if _get_config_fn is None:
        return _DEFAULT_PRESSURE_BUDGET
    raw = (_get_config_fn("flows.pressure_budget") or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_PRESSURE_BUDGET


# ── DB-touching helpers (commit-free) ────────────────────────────────────────────

def count_recent_automated_sends(conn, person_id: str, *, days: int = _PRESSURE_WINDOW_DAYS) -> int:
    """How many automated (agent/flow/cron) outbound messages this person has
    received in the last `days` days, across every system."""
    like_clauses = " OR ".join("sent_by LIKE %s" for _ in _AUTOMATED_SENT_BY_PREFIXES)
    params = [f"{p}%" for p in _AUTOMATED_SENT_BY_PREFIXES]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM outbound_messages "
            f"WHERE person_id = %s AND sent_at >= NOW() - (%s * interval '1 day') "
            f"  AND ({like_clauses})",
            (person_id, days, *params),
        )
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def fetch_recent_inbound_text(
    conn, person_id: str, channel: str, *, within_hours: int = 24,
) -> str | None:
    """Best-effort: the most recent INBOUND message body for this person on
    this channel within the window, for the crisis check. None on no match or
    any failure — never raises (mirrors the codebase's best-effort discipline
    for anything gating a send, per _channel_send_eligibility)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT m.body FROM messages m JOIN sessions s ON s.id = m.session_id "
                "WHERE s.person_id = %s AND s.channel = %s AND m.role = 'user' "
                "  AND m.created_at >= NOW() - (%s * interval '1 hour') "
                "ORDER BY m.created_at DESC LIMIT 1",
                (person_id, channel, within_hours),
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.warning("[policy] fetch_recent_inbound_text failed for %s: %s", person_id, e)
        return None


# ── The gate ──────────────────────────────────────────────────────────────────

def evaluate_send(
    conn,
    *,
    person_id: str,
    channel: str = "whatsapp",
    now: datetime.datetime | None = None,
) -> PolicyVerdict:
    """The Policy Gate. First veto wins; see module docstring for order."""
    if _is_crisis_fn is not None:
        recent = fetch_recent_inbound_text(conn, person_id, channel)
        if recent and _is_crisis_fn(recent):
            return PolicyVerdict(
                False, "crisis",
                "a recent inbound message signaled crisis — automation stands down",
            )

    budget = pressure_budget()
    sent = count_recent_automated_sends(conn, person_id)
    if sent >= budget:
        return PolicyVerdict(
            False, "pressure_budget",
            f"{sent}/{budget} automated messages in the last {_PRESSURE_WINDOW_DAYS}d",
        )

    if quiet_hours_block(now):
        return PolicyVerdict(
            False, "quiet_hours",
            f"{_QUIET_START_HOUR}:00-{_QUIET_END_HOUR:02d}:00 Asia/Jerusalem",
        )

    if _channel_eligibility_fn is not None:
        elig = _channel_eligibility_fn(conn, person_id, channel)
        if not elig.get("eligible"):
            return PolicyVerdict(
                False, elig.get("reason") or "channel_ineligible",
                "channel send-window check failed",
            )

    return PolicyVerdict(True)


def guarded_whatsapp_send(
    conn,
    *,
    person_id: str,
    text: str,
    source: str,
    opportunity_id: str | None = None,
    flow_slug: str | None = None,
    trigger: dict | None = None,
) -> SendOutcome:
    """Evaluate (Policy Gate, then the Verifier Loop panel) + (if allowed)
    send + persist to outbound_messages + log the 'contacted' interaction —
    the ONE path every automated WhatsApp send should use. `source` becomes
    outbound_messages.sent_by — MUST start with 'agent:' / 'flow:' / 'cron:'
    (asserted) so the pressure-budget count sees it and it's visually
    distinct from a manual operator send in the thread.

    flow_slug/trigger are optional run context — when present, the panel's
    staleness verifier re-checks the trigger predicate against live signals.
    Commit-free — caller owns the transaction, matching the rest of the
    codebase's send call sites (qualification_agent, route_and_send)."""
    if not source.startswith(_AUTOMATED_SENT_BY_PREFIXES):
        raise ValueError(
            f"guarded_whatsapp_send: source={source!r} must start with one of "
            f"{_AUTOMATED_SENT_BY_PREFIXES} — this is what makes it count "
            "against the pressure budget and read as automated in the thread."
        )

    verdict = evaluate_send(conn, person_id=person_id, channel="whatsapp")
    if not verdict.allowed:
        logger.info(
            "[policy] blocked send to %s (source=%s): %s — %s",
            person_id, source, verdict.reason, verdict.detail,
        )
        flow_memory.record_failure(
            "policy_blocked", flow_slug=flow_slug or source, person_id=person_id,
            reason=verdict.reason, detail=verdict.detail,
        )
        return SendOutcome(sent=False, verdict=verdict)

    # The Verifier Loop — the multi-agent review panel (nexus/flows/verifier.py).
    verification = flow_verifier.verify_send(
        conn, person_id=person_id, text=text, source=source,
        flow_slug=flow_slug, trigger=trigger,
    )
    if not verification.approved:
        blocking = verification.blocking
        logger.info(
            "[policy] verifier %s send to %s (source=%s): %s — %s",
            verification.decision, person_id, source,
            blocking.reason if blocking else "?", blocking.detail if blocking else "",
        )
        reason_prefix = "verifier" if verification.decision == "reject" else "verifier_defer"
        return SendOutcome(
            sent=False,
            verdict=PolicyVerdict(
                False,
                f"{reason_prefix}:{blocking.reason if blocking else 'unknown'}",
                blocking.detail if blocking else "",
            ),
            verification=verification,
            defer_hours=blocking.defer_hours if blocking else None,
        )

    recipient = nexus_identity.resolve_whatsapp_recipient(conn, person_id)
    if not recipient:
        return SendOutcome(
            sent=False,
            verdict=PolicyVerdict(False, "no_whatsapp_number", "no reachable WhatsApp identity"),
            verification=verification,
        )

    resp = nexus_whatsapp.send_text(recipient, text)
    if resp is None:
        flow_memory.record_failure(
            "send_failed", flow_slug=flow_slug or source, person_id=person_id,
            reason="transport_no_response",
        )
        return SendOutcome(
            sent=False,
            verdict=PolicyVerdict(False, "send_failed", "channel transport returned no response"),
            verification=verification,
        )

    message_id = _extract_wamid(resp)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outbound_messages "
            "(person_id, opportunity_id, channel, body, provider_message_id, sent_by) "
            "VALUES (%s, %s, 'whatsapp', %s, %s, %s)",
            (person_id, opportunity_id, text, message_id, source),
        )
    nexus_interactions.log_interaction(
        conn, "contacted", "whatsapp", person_id=person_id,
        payload={"by": source, "via": "policy_gate", "message_id": message_id, "length": len(text)},
    )
    return SendOutcome(sent=True, verdict=verdict, provider_message_id=message_id,
                       verification=verification)


def notify_operator(text: str) -> str | None:
    """DM Erez on Telegram — the human-in-the-loop node. Bridged, not
    Policy-Gate-checked (an internal operational notification is not a
    lead-facing send; nothing here touches a lead's pressure budget or the
    crisis/quiet-hours checks meant to protect leads, not Erez)."""
    if _notify_operator_fn is None:
        logger.warning("[policy] notify_operator called before configure()")
        return None
    return _notify_operator_fn(text)


def _extract_wamid(resp: str | None) -> str | None:
    """Best-effort pull of the wamid from a Meta/Kapso send response — the
    single extraction point now that guarded_whatsapp_send is the one path
    every automated WhatsApp send uses (agents, flows, crons)."""
    try:
        msgs = (json.loads(resp or "") or {}).get("messages") or []
        return msgs[0].get("id") if msgs else None
    except Exception:
        return None
