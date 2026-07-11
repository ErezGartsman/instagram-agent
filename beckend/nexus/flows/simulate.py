"""
nexus.flows.simulate — the 90-day time-travel simulation
(SYSTEM_ELEVATION_PRD.md §B6/§F3: "replay a draft flow against the last 90
days of real events before it touches a human … Publishing requires a
simulation pass").

The moat, and the reason it's nearly free: `interactions` is an append-only
historical log with `occurred_at`, so we can reconstruct WHEN a flow's trigger
would have fired in the past, then dry-run the flow graph at each of those
moments — evaluating the safety layers AS-OF that historical timestamp — and
tally the impact:

    "would have fired 34 times · sent 28 · 6 blocked (4 pressure budget,
     2 quiet hours) · advanced 11 stages"

DESIGN — pure core + thin IO (mirrors predicates/signals):
  • candidate reconstruction and the graph dry-run are PURE functions over
    already-fetched history, so they're unit-tested without DB gymnastics;
  • the send-node policy verdict is an INJECTED callable, so the dry-run stays
    pure and the as-of DB queries live in one place.

HONESTY (documented in the report's `notes`, never hidden):
  • Event triggers reconstruct EXACTLY — every historical interaction of the
    kind is a real fire moment.
  • State triggers reconstruct "cooling episodes" from each person's interaction
    timeline + stage history, evaluating the ACTUAL predicate DSL against a
    reconstructed as-of signal. Fields the log can't reconstruct (urgency,
    waiting_on — reserved/None in V1 anyway) are None, exactly as live.
  • The verifier-loop CONTENT checks (duplicate/booking) are not replayed —
    the report scopes itself to trigger-fire frequency and the Policy Gate
    (crisis/pressure/quiet-hours), which is what gates the publish decision.

Read-only: no writes, no sends, ever. Commit-free.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

from nexus.flows import policy as flow_policy
from nexus.flows import predicates as flow_predicates

logger = logging.getLogger("nexus.flows.simulate")

DEFAULT_WINDOW_DAYS = 90
# Guardrails so a simulation can never exceed a request budget on a huge DB.
_MAX_PERSONS = 5000
_MAX_INTERACTIONS = 50_000
_SAMPLE_SIZE = 8


@dataclass
class Candidate:
    """One reconstructed historical fire moment."""
    person_id: str
    at: datetime.datetime
    signals: dict


@dataclass
class Outcome:
    person_id: str
    at: datetime.datetime
    # 'would_send' | 'would_notify' | 'advanced' | 'noted' | 'flagged' |
    # 'blocked' | 'ended' (a condition sent it down a dead branch)
    result: str
    reason: str | None = None   # the Policy Gate reason on 'blocked'


@dataclass
class Report:
    window_days: int
    trigger_type: str
    fires: int = 0
    actions: dict = field(default_factory=dict)
    blocked: int = 0
    blocked_by: dict = field(default_factory=dict)
    sample: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "window_days": self.window_days,
            "trigger_type": self.trigger_type,
            "fires": self.fires,
            "actions": self.actions,
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "sample": self.sample,
            "notes": self.notes,
        }


# ── Pure core ─────────────────────────────────────────────────────────────────

def event_candidates(rows: list[tuple]) -> list[Candidate]:
    """rows = [(person_id, occurred_at), …] for interactions of the trigger's
    kind. Each is an exact historical fire. Event flows carry no per-fire
    signals (their trigger is a fact, not a condition)."""
    return [Candidate(str(pid), at, {}) for pid, at in rows if pid and at]


def reconstruct_state_candidates(
    timelines: dict[str, list[dict]],
    predicate: dict,
    *,
    window_start: datetime.datetime,
    now: datetime.datetime,
) -> list[Candidate]:
    """Reconstruct state-trigger fires from per-person interaction timelines.

    timelines[person_id] = [{"at": dt, "kind": str, "payload": dict}, …]
    ordered oldest→newest. Stage history comes from kind='stage_change'
    payloads ({from,to}); the gap AFTER each interaction is a candidate
    cooling window. We sample at (interaction.at + cooling_threshold) and
    evaluate the REAL predicate against the reconstructed as-of signal.
    """
    threshold_h = _cooling_threshold_hours(predicate)
    out: list[Candidate] = []
    for person_id, events in timelines.items():
        if not events:
            continue
        stage = None
        stage_since = events[0]["at"]
        for i, ev in enumerate(events):
            if ev["kind"] == "stage_change":
                to = (ev.get("payload") or {}).get("to")
                if to:
                    stage = to
                    stage_since = ev["at"]
            # The cooling window opens at this interaction and closes at the
            # next one (or `now` if it's the person's last interaction).
            gap_end = events[i + 1]["at"] if i + 1 < len(events) else now
            fire_at = ev["at"] + datetime.timedelta(hours=threshold_h)
            if fire_at > gap_end or fire_at > now or fire_at < window_start:
                continue
            signals = {
                "stage": stage,
                "hours_since_last": (fire_at - ev["at"]).total_seconds() / 3600.0,
                "hours_in_stage": (fire_at - stage_since).total_seconds() / 3600.0,
                "channel": None,
                "urgency": None,
                "waiting_on": None,
            }
            try:
                if flow_predicates.evaluate(predicate, signals):
                    out.append(Candidate(person_id, fire_at, signals))
            except flow_predicates.PredicateError:
                # A malformed predicate can't fire anywhere — stop cleanly.
                return out
    return out


def _cooling_threshold_hours(predicate: dict) -> float:
    """The largest hours_since_last / hours_in_stage `gte`/`gt` threshold in
    the predicate — the "cooling" duration to sample after. Defaults to a
    small offset so a threshold-less state flow samples just after each
    interaction (fires eagerly, matching live dispatch_states)."""
    best = 0.0
    found = False

    def walk(node):
        nonlocal best, found
        if not isinstance(node, dict):
            return
        for comb in ("all", "any"):
            if comb in node and isinstance(node[comb], list):
                for c in node[comb]:
                    walk(c)
        if "not" in node:
            walk(node["not"])
        if node.get("field") in ("hours_since_last", "hours_in_stage") \
                and node.get("op") in ("gte", "gt"):
            try:
                v = float(node.get("value"))
                found = True
                best = max(best, v)
            except (TypeError, ValueError):
                pass

    walk(predicate)
    return best if found else 0.25


def dry_run(graph: dict, candidate: Candidate, *, send_check) -> Outcome:
    """Walk the graph for one candidate without side effects. `send_check` is
    an injected callable (person_id, at, body) -> (allowed: bool,
    reason: str|None) — the as-of Policy Gate for send nodes. Returns the
    first terminal action's Outcome (V1 flows are short chains)."""
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    cursor = _entry(graph)
    steps = 0
    while cursor and steps < 50:
        steps += 1
        node = nodes.get(cursor)
        if node is None:
            return Outcome(candidate.person_id, candidate.at, "ended")
        t = node.get("type")

        if t == "action:send_message":
            allowed, reason = send_check(candidate.person_id, candidate.at, node.get("body", ""))
            if allowed:
                return Outcome(candidate.person_id, candidate.at, "would_send")
            return Outcome(candidate.person_id, candidate.at, "blocked", reason)
        if t == "action:notify_operator":
            return Outcome(candidate.person_id, candidate.at, "would_notify")
        if t == "action:advance_stage":
            return Outcome(candidate.person_id, candidate.at, "advanced")
        if t == "action:add_note":
            return Outcome(candidate.person_id, candidate.at, "noted")
        if t == "action:set_flag":
            return Outcome(candidate.person_id, candidate.at, "flagged")

        # Structural nodes — advance the cursor.
        if t == "condition":
            branch = "true"
            try:
                branch = "true" if flow_predicates.evaluate(node.get("predicate") or {}, candidate.signals) else "false"
            except flow_predicates.PredicateError:
                branch = "false"
            cursor = _edge_to(edges, cursor, when=branch)
        else:  # trigger, wait, anything else structural
            cursor = _edge_to(edges, cursor)
    return Outcome(candidate.person_id, candidate.at, "ended")


def _entry(graph: dict) -> str | None:
    for n in graph.get("nodes", []):
        if n.get("type") == "trigger":
            return n["id"]
    nodes = graph.get("nodes", [])
    return nodes[0]["id"] if nodes else None


def _edge_to(edges: list, frm: str, *, when: str | None = None) -> str | None:
    matches = [e for e in edges if e.get("from") == frm]
    if when is not None:
        for e in matches:
            if e.get("when") == when:
                return e.get("to")
        return None
    return matches[0].get("to") if matches else None


def aggregate(outcomes: list[Outcome], *, window_days: int, trigger_type: str,
              names: dict[str, str], notes: list[str]) -> Report:
    """Tally outcomes into the report the publish dialog renders."""
    rep = Report(window_days=window_days, trigger_type=trigger_type, notes=notes)
    rep.fires = len(outcomes)
    action_keys = ("would_send", "would_notify", "advanced", "noted", "flagged")
    rep.actions = {k: 0 for k in action_keys}
    for o in outcomes:
        if o.result in rep.actions:
            rep.actions[o.result] += 1
        elif o.result == "blocked":
            rep.blocked += 1
            rep.blocked_by[o.reason or "unknown"] = rep.blocked_by.get(o.reason or "unknown", 0) + 1
    # A representative sample, blocked first (the interesting ones), newest first.
    ranked = sorted(
        outcomes,
        key=lambda o: (0 if o.result == "blocked" else 1, -o.at.timestamp()),
    )
    for o in ranked[:_SAMPLE_SIZE]:
        rep.sample.append({
            "person_name": names.get(o.person_id, "Lead"),
            "at": o.at.isoformat(),
            "outcome": o.result,
            "reason": o.reason,
        })
    return rep


# ── IO orchestrator ───────────────────────────────────────────────────────────

def simulate_flow(
    conn, *, trigger: dict, graph: dict,
    days: int = DEFAULT_WINDOW_DAYS,
    now: datetime.datetime | None = None,
) -> dict:
    """Run the full simulation and return the report dict. Read-only,
    commit-free. `now` is injectable for deterministic tests."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    window_start = now - datetime.timedelta(days=days)
    ttype = trigger.get("type")
    notes: list[str] = []

    if ttype == "event":
        kind = trigger.get("kind")
        candidates = event_candidates(_fetch_event_rows(conn, kind, window_start))
        notes.append(f"Event trigger — every '{kind}' interaction in the window is an exact historical fire.")
    elif ttype == "state":
        predicate = trigger.get("predicate") or {}
        try:
            flow_predicates.validate(predicate)
        except flow_predicates.PredicateError as e:
            return Report(days, "state", notes=[f"Invalid predicate: {e}"]).as_dict()
        timelines = _fetch_timelines(conn, window_start)
        candidates = reconstruct_state_candidates(timelines, predicate, window_start=window_start, now=now)
        notes.append("State trigger — cooling episodes reconstructed from the interaction log; "
                     "the real predicate is evaluated against each reconstructed as-of signal.")
    else:
        return Report(days, str(ttype), notes=["Unknown trigger type — nothing to simulate."]).as_dict()

    send_check = _make_send_check(conn)
    outcomes = [dry_run(graph, c, send_check=send_check) for c in candidates]

    names = _fetch_names(conn, {o.person_id for o in outcomes})
    return aggregate(outcomes, window_days=days, trigger_type=str(ttype),
                     names=names, notes=notes).as_dict()


def _make_send_check(conn):
    """Build the as-of Policy Gate for send nodes: crisis → pressure → quiet,
    each evaluated as of the candidate's historical timestamp."""
    budget = flow_policy.pressure_budget()

    def check(person_id: str, at: datetime.datetime, body: str):
        if _crisis_as_of(conn, person_id, at):
            return False, "crisis"
        if _automated_sends_before(conn, person_id, at) >= budget:
            return False, "pressure_budget"
        if flow_policy.quiet_hours_block(at):
            return False, "quiet_hours"
        return True, None

    return check


# ── As-of DB reads (the only IO; kept together, commit-free) ──────────────────

def _fetch_event_rows(conn, kind: str, window_start) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id, occurred_at FROM interactions "
            "WHERE kind = %s AND person_id IS NOT NULL AND occurred_at >= %s "
            "ORDER BY occurred_at ASC LIMIT %s",
            (kind, window_start, _MAX_INTERACTIONS),
        )
        return cur.fetchall()


def _fetch_timelines(conn, window_start) -> dict[str, list[dict]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id, occurred_at, kind, payload FROM interactions "
            "WHERE person_id IS NOT NULL AND occurred_at >= %s "
            "ORDER BY person_id, occurred_at ASC LIMIT %s",
            (window_start, _MAX_INTERACTIONS),
        )
        rows = cur.fetchall()
    timelines: dict[str, list[dict]] = {}
    for person_id, at, kind, payload in rows:
        pid = str(person_id)
        if pid not in timelines and len(timelines) >= _MAX_PERSONS:
            continue
        timelines.setdefault(pid, []).append(
            {"at": at, "kind": kind, "payload": payload if isinstance(payload, dict) else {}}
        )
    return timelines


def _crisis_as_of(conn, person_id: str, at) -> bool:
    """Was there a crisis-signalling inbound in the 24h before `at`?"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT m.body FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE s.person_id = %s AND m.role = 'user' "
            "  AND m.created_at <= %s AND m.created_at >= %s - interval '24 hours' "
            "ORDER BY m.created_at DESC LIMIT 1",
            (person_id, at, at),
        )
        row = cur.fetchone()
    return bool(row and flow_policy.detect_crisis(row[0]))


def _automated_sends_before(conn, person_id: str, at) -> int:
    """Automated (agent/flow/cron) outbound to this person in the 7d before `at`."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM outbound_messages "
            "WHERE person_id = %s AND sent_at <= %s "
            "  AND sent_at >= %s - interval '7 days' "
            "  AND (sent_by LIKE 'agent:%%' OR sent_by LIKE 'flow:%%' OR sent_by LIKE 'cron:%%')",
            (person_id, at, at),
        )
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _fetch_names(conn, person_ids: set[str]) -> dict[str, str]:
    if not person_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, display_name FROM person WHERE id = ANY(%s)",
            (list(person_ids),),
        )
        return {str(pid): (name or "Lead") for pid, name in cur.fetchall()}
