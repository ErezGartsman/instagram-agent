"""
nexus.flows.verifier — the Verifier Loop: an isolated, multi-agent review
panel that re-examines every proposed outward send against the actual
interaction record before the transport is touched.

WHY A SECOND LAYER when the Policy Gate exists: the gate answers "is this
person protected right now" (crisis / pressure budget / quiet hours /
channel window). The verifiers answer a different question — "does this
specific action still make sense given what has ACTUALLY happened since it
was decided". They close the F1 review's biggest gap: state-trigger runs
were dispatched on a snapshot and executed blind, so a lead who replied
between sweeps would still get the nudge.

THE PANEL (each verifier is an isolated agent with one narrow mandate):
  staleness         — for state-triggered runs: re-evaluate the trigger
                      predicate against LIVE signals at execution time; the
                      world may have moved since dispatch.        -> reject
  duplicate_content — the proposed body (normalized) already went to this
                      person recently, by ANY sender.             -> reject
  upcoming_booking  — the person already has a scheduled booking; a
                      re-engagement nudge now reads as a broken
                      system, not attentiveness.                  -> reject
  recent_inbound    — the person wrote in very recently; they're mid-
                      conversation (possibly with Erez, live). Automation
                      should yield, then retry.                   -> defer
  circuit_breaker   — the engine's own failure memory shows repeated
                      recent rejections for this (flow, person); stop
                      re-attempting a losing pattern.             -> reject

AGGREGATION SEMANTICS — a true panel, not a short-circuit chain: EVERY
verifier runs and reports (their independent verdicts are all recorded on
the flow_run_steps output / shadow record — this is exactly the review data
shadow mode exists to produce). The aggregator then decides:
reject > defer > approve, first-in-registry-order picking the blocking
verdict. A verifier that CRASHES abstains (fail-open) and the crash is
recorded to failure memory — verifiers are advisory reviewers layered on a
fail-closed Policy Gate, so a verifier bug must degrade to "no extra
protection", never to "engine halted".

All checks are deterministic reads (SQL + file memory) — no LLM calls in a
sweep path that runs unattended against real leads. The registry is the
extension seam: an `ai_review` verifier can be appended later behind the
existing planner/copilot LLM seams once real send volume justifies its
latency, cost, and mocking burden.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from nexus.flows import memory as flow_memory
from nexus.flows import predicates as flow_predicates
from nexus.flows import signals as flow_signals

logger = logging.getLogger("nexus.flows.verifier")

# duplicate_content: window + how many recent outbound bodies to compare.
_DUPLICATE_WINDOW_DAYS = 7
_DUPLICATE_COMPARE_LIMIT = 10
# recent_inbound: an inbound message within this window defers the send.
_RECENT_INBOUND_HOURS = 2
_DEFER_HOURS = 2.0
# circuit_breaker: this many recorded failures for (flow, person) in the
# window opens the circuit. Breaker-caused rejections are EXCLUDED from the
# count (a breaker that feeds on its own output never closes again).
_CIRCUIT_THRESHOLD = 3
_CIRCUIT_WINDOW_DAYS = 7
_BREAKER_REASON = "circuit_breaker"


@dataclass(frozen=True)
class VerifierVerdict:
    verifier: str
    decision: str            # 'approve' | 'reject' | 'defer' | 'error'
    reason: str | None = None
    detail: str = ""
    defer_hours: float | None = None

    def as_dict(self) -> dict:
        d = {"verifier": self.verifier, "decision": self.decision}
        if self.reason:
            d["reason"] = self.reason
        if self.detail:
            d["detail"] = self.detail
        if self.defer_hours is not None:
            d["defer_hours"] = self.defer_hours
        return d


@dataclass
class SendVerification:
    decision: str                              # aggregate: 'approve' | 'reject' | 'defer'
    verdicts: list[VerifierVerdict] = field(default_factory=list)
    blocking: VerifierVerdict | None = None    # the decisive verdict, when not approved

    @property
    def approved(self) -> bool:
        return self.decision == "approve"

    def as_dict(self) -> dict:
        d = {"decision": self.decision, "verdicts": [v.as_dict() for v in self.verdicts]}
        if self.blocking:
            d["blocking"] = self.blocking.as_dict()
        return d


# ── The verifiers ─────────────────────────────────────────────────────────────

def _verify_staleness(conn, ctx: dict) -> VerifierVerdict:
    """State-triggered runs only: does the trigger predicate STILL hold
    against live signals? Event/manual triggers abstain (their trigger is a
    fact that happened, not a condition that must persist)."""
    trigger = ctx.get("trigger") or {}
    if trigger.get("type") != "state" or not trigger.get("predicate"):
        return VerifierVerdict("staleness", "approve", detail="not a state trigger")
    live = flow_signals.signals_for(conn, ctx["person_id"])
    if live is None:
        return VerifierVerdict(
            "staleness", "reject", reason="stale_trigger",
            detail="no open opportunity anymore — the episode closed since dispatch",
        )
    still_true = flow_predicates.evaluate(trigger["predicate"], live)
    if not still_true:
        return VerifierVerdict(
            "staleness", "reject", reason="stale_trigger",
            detail="trigger predicate no longer holds against live signals",
        )
    return VerifierVerdict("staleness", "approve")


_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip()).lower()


def _verify_duplicate_content(conn, ctx: dict) -> VerifierVerdict:
    """Has this exact (normalized) body already gone to this person recently
    — by any sender, manual or automated?"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT body FROM outbound_messages "
            "WHERE person_id = %s AND sent_at >= NOW() - (%s * interval '1 day') "
            "ORDER BY sent_at DESC LIMIT %s",
            (ctx["person_id"], _DUPLICATE_WINDOW_DAYS, _DUPLICATE_COMPARE_LIMIT),
        )
        rows = cur.fetchall()
    proposed = _normalize(ctx["text"])
    for (body,) in rows:
        if _normalize(body) == proposed:
            return VerifierVerdict(
                "duplicate_content", "reject", reason="duplicate_content",
                detail=f"identical message already sent within {_DUPLICATE_WINDOW_DAYS}d",
            )
    return VerifierVerdict("duplicate_content", "approve")


def _verify_upcoming_booking(conn, ctx: dict) -> VerifierVerdict:
    """A person with a scheduled future booking has already converted —
    automated outreach now reads as a system that doesn't know its own
    state."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM bookings "
            "WHERE person_id = %s AND status = 'scheduled' AND starts_at > NOW() "
            "LIMIT 1",
            (ctx["person_id"],),
        )
        row = cur.fetchone()
    if row:
        return VerifierVerdict(
            "upcoming_booking", "reject", reason="upcoming_booking",
            detail="a scheduled booking exists — nothing to chase",
        )
    return VerifierVerdict("upcoming_booking", "approve")


def _verify_recent_inbound(conn, ctx: dict) -> VerifierVerdict:
    """An inbound message in the last couple of hours means the person is
    mid-conversation (possibly with Erez, live). Yield and retry later —
    defer, not reject."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE s.person_id = %s AND m.role = 'user' "
            "  AND m.created_at >= NOW() - (%s * interval '1 hour') "
            "LIMIT 1",
            (ctx["person_id"], _RECENT_INBOUND_HOURS),
        )
        row = cur.fetchone()
    if row:
        return VerifierVerdict(
            "recent_inbound", "defer", reason="recent_inbound_activity",
            detail=f"inbound within {_RECENT_INBOUND_HOURS}h — the conversation is live",
            defer_hours=_DEFER_HOURS,
        )
    return VerifierVerdict("recent_inbound", "approve")


def _verify_circuit_breaker(conn, ctx: dict) -> VerifierVerdict:
    """Consult the engine's own failure memory: repeated recent
    rejections/blocks for this (flow, person) mean the pattern is losing —
    stop re-attempting it. Empty memory (fresh instance, Vercel recycle)
    approves: the breaker only ever ADDS protection it has evidence for."""
    slug = ctx.get("flow_slug") or ctx.get("source")
    count = flow_memory.failure_count(
        flow_slug=slug, person_id=ctx["person_id"],
        within_days=_CIRCUIT_WINDOW_DAYS, exclude_reasons=(_BREAKER_REASON,),
    )
    if count >= _CIRCUIT_THRESHOLD:
        flow_memory.record_lesson(
            f"circuit opened: flow={slug} person={ctx['person_id']} — "
            f"{count} failed/blocked attempts in {_CIRCUIT_WINDOW_DAYS}d; "
            "suppressing further attempts for this pairing",
            tags=["circuit_breaker", str(slug)],
        )
        return VerifierVerdict(
            "circuit_breaker", "reject", reason=_BREAKER_REASON,
            detail=f"{count} recorded failures in {_CIRCUIT_WINDOW_DAYS}d for this flow+person",
        )
    return VerifierVerdict("circuit_breaker", "approve")


# Registry order IS aggregation priority for picking the blocking verdict.
_REGISTRY = (
    _verify_staleness,
    _verify_duplicate_content,
    _verify_upcoming_booking,
    _verify_recent_inbound,
    _verify_circuit_breaker,
)


# ── The loop ──────────────────────────────────────────────────────────────────

def verify_send(
    conn,
    *,
    person_id: str,
    text: str,
    source: str,
    flow_slug: str | None = None,
    trigger: dict | None = None,
    record: bool = True,
) -> SendVerification:
    """Run the full panel and aggregate. Commit-free (reads only).

    record=True (live sends) writes reject/defer outcomes to failure memory —
    the circuit breaker's food. Shadow-mode callers pass record=False so a
    flow that is merely being OBSERVED cannot open a real circuit.
    """
    ctx = {"person_id": person_id, "text": text, "source": source,
           "flow_slug": flow_slug, "trigger": trigger}

    verdicts: list[VerifierVerdict] = []
    for fn in _REGISTRY:
        try:
            verdicts.append(fn(conn, ctx))
        except Exception as e:
            # Isolated: one crashed reviewer abstains; the panel continues.
            name = fn.__name__.removeprefix("_verify_")
            logger.warning("[verifier] %s crashed for person=%s: %s", name, person_id, e)
            verdicts.append(VerifierVerdict(name, "error", detail=f"{type(e).__name__}: {e}"))
            flow_memory.record_failure(
                "verifier_error", flow_slug=flow_slug, person_id=person_id,
                verifier=name, reason="verifier_crashed", detail=str(e),
            )

    blocking = next((v for v in verdicts if v.decision == "reject"), None) \
        or next((v for v in verdicts if v.decision == "defer"), None)
    decision = blocking.decision if blocking else "approve"
    result = SendVerification(decision=decision, verdicts=verdicts, blocking=blocking)

    if record and blocking is not None:
        flow_memory.record_failure(
            "send_rejected" if decision == "reject" else "send_deferred",
            flow_slug=flow_slug or source, person_id=person_id,
            verifier=blocking.verifier, reason=blocking.reason, detail=blocking.detail,
        )
    return result
