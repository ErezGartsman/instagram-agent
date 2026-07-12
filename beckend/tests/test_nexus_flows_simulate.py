"""
tests.test_nexus_flows_simulate — the 90-day simulation. The reconstruction +
dry-run + aggregation are pure, so they're tested directly; the as-of policy
checks are tested through an injected send_check. simulate_flow's IO layer is
covered with FakeConn.
"""
import datetime

import pytest

from nexus.flows import simulate
from nexus.flows.simulate import (
    Candidate, Outcome, aggregate, dry_run, event_candidates,
    reconstruct_state_candidates, _cooling_threshold_hours,
)
from tests._flows_fakes import FakeConn

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
WINDOW_START = NOW - datetime.timedelta(days=90)

NOTIFY_GRAPH = {
    "nodes": [{"id": "t1", "type": "trigger"},
              {"id": "n1", "type": "action:notify_operator", "body": "check in"}],
    "edges": [{"from": "t1", "to": "n1"}],
}
SEND_GRAPH = {
    "nodes": [{"id": "t1", "type": "trigger"},
              {"id": "n1", "type": "action:send_message", "body": "hi there"}],
    "edges": [{"from": "t1", "to": "n1"}],
}
COOLING_PREDICATE = {
    "all": [
        {"field": "stage", "op": "in", "value": ["qualified", "captured", "briefed"]},
        {"field": "hours_since_last", "op": "gte", "value": 36},
    ],
}


def _always_send(pid, at, body):
    return True, None


def _always_block(reason):
    def check(pid, at, body):
        return False, reason
    return check


class TestEventCandidates:
    def test_maps_rows_exactly(self):
        rows = [("p1", NOW), ("p2", NOW - datetime.timedelta(days=1))]
        cands = event_candidates(rows)
        assert [c.person_id for c in cands] == ["p1", "p2"]
        assert cands[0].signals == {}

    def test_drops_rows_missing_person_or_time(self):
        assert event_candidates([(None, NOW), ("p1", None)]) == []


class TestCoolingThreshold:
    def test_extracts_max_gte_hours(self):
        assert _cooling_threshold_hours(COOLING_PREDICATE) == 36

    def test_defaults_when_no_hours_threshold(self):
        assert _cooling_threshold_hours({"field": "stage", "op": "eq", "value": "qualified"}) == 0.25

    def test_takes_the_largest_across_branches(self):
        pred = {"any": [
            {"field": "hours_since_last", "op": "gte", "value": 24},
            {"field": "hours_in_stage", "op": "gt", "value": 72},
        ]}
        assert _cooling_threshold_hours(pred) == 72


class TestReconstructStateCandidates:
    def test_a_cooling_episode_fires_once(self):
        # Person entered 'qualified' then went quiet: last interaction at day-40,
        # next interaction never (→ now). 36h after the last touch, it fires.
        entered = NOW - datetime.timedelta(days=40)
        timelines = {
            "p1": [
                {"at": entered, "kind": "stage_change", "payload": {"to": "qualified"}},
            ],
        }
        cands = reconstruct_state_candidates(timelines, COOLING_PREDICATE,
                                             window_start=WINDOW_START, now=NOW)
        assert len(cands) == 1
        assert cands[0].person_id == "p1"
        assert cands[0].signals["stage"] == "qualified"
        assert cands[0].signals["hours_since_last"] == 36.0
        # fires 36h after the entry
        assert cands[0].at == entered + datetime.timedelta(hours=36)

    def test_no_fire_when_no_gap_reaches_threshold(self):
        # A steady contact cadence right up to now — every gap (incl. the
        # trailing gap to now) is < 36h, so the lead never "cools".
        timelines = {
            "p1": [
                {"at": NOW - datetime.timedelta(hours=30), "kind": "stage_change", "payload": {"to": "qualified"}},
                {"at": NOW - datetime.timedelta(hours=20), "kind": "contacted", "payload": {}},
                {"at": NOW - datetime.timedelta(hours=10), "kind": "contacted", "payload": {}},
            ],
        }
        cands = reconstruct_state_candidates(timelines, COOLING_PREDICATE,
                                             window_start=WINDOW_START, now=NOW)
        assert cands == []

    def test_a_quiet_gap_after_a_reply_still_fires(self):
        # The behavior the previous test got wrong: after a reply the lead
        # goes quiet 36h+ → that trailing gap IS a real cooling episode.
        t0 = NOW - datetime.timedelta(days=5)
        timelines = {
            "p1": [
                {"at": t0, "kind": "stage_change", "payload": {"to": "qualified"}},
                {"at": t0 + datetime.timedelta(hours=10), "kind": "contacted", "payload": {}},
            ],
        }
        cands = reconstruct_state_candidates(timelines, COOLING_PREDICATE,
                                             window_start=WINDOW_START, now=NOW)
        assert len(cands) == 1  # fires 36h after the last touch

    def test_no_fire_when_stage_does_not_match(self):
        entered = NOW - datetime.timedelta(days=40)
        timelines = {
            "p1": [{"at": entered, "kind": "stage_change", "payload": {"to": "engaged"}}],
        }
        cands = reconstruct_state_candidates(timelines, COOLING_PREDICATE,
                                             window_start=WINDOW_START, now=NOW)
        assert cands == []  # 'engaged' not in the predicate's stage set

    def test_malformed_predicate_stops_cleanly(self):
        entered = NOW - datetime.timedelta(days=40)
        timelines = {"p1": [{"at": entered, "kind": "stage_change", "payload": {"to": "qualified"}}]}
        bad = {"field": "not_a_field", "op": "eq", "value": 1}
        assert reconstruct_state_candidates(timelines, bad, window_start=WINDOW_START, now=NOW) == []


class TestDryRun:
    def test_notify_flow_would_notify(self):
        c = Candidate("p1", NOW, {})
        out = dry_run(NOTIFY_GRAPH, c, send_check=_always_send)
        assert out.result == "would_notify"

    def test_send_flow_would_send_when_allowed(self):
        c = Candidate("p1", NOW, {})
        out = dry_run(SEND_GRAPH, c, send_check=_always_send)
        assert out.result == "would_send"

    def test_send_flow_blocked_carries_reason(self):
        c = Candidate("p1", NOW, {})
        out = dry_run(SEND_GRAPH, c, send_check=_always_block("quiet_hours"))
        assert out.result == "blocked"
        assert out.reason == "quiet_hours"

    def test_condition_true_branch(self):
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "c1", "type": "condition", "predicate": {"field": "stage", "op": "eq", "value": "qualified"}},
                {"id": "send", "type": "action:send_message", "body": "hi"},
                {"id": "note", "type": "action:add_note", "note": "x"},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "send", "when": "true"},
                {"from": "c1", "to": "note", "when": "false"},
            ],
        }
        c = Candidate("p1", NOW, {"stage": "qualified"})
        assert dry_run(graph, c, send_check=_always_send).result == "would_send"
        c2 = Candidate("p1", NOW, {"stage": "engaged"})
        assert dry_run(graph, c2, send_check=_always_send).result == "noted"

    def test_wait_node_is_traversed_not_terminal(self):
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "w1", "type": "wait", "hours": 24},
                {"id": "n1", "type": "action:notify_operator", "body": "x"},
            ],
            "edges": [{"from": "t1", "to": "w1"}, {"from": "w1", "to": "n1"}],
        }
        assert dry_run(graph, Candidate("p1", NOW, {}), send_check=_always_send).result == "would_notify"


class TestAggregate:
    def test_tallies_actions_and_blocks(self):
        outs = [
            Outcome("p1", NOW, "would_send"),
            Outcome("p2", NOW, "would_send"),
            Outcome("p3", NOW, "blocked", "pressure_budget"),
            Outcome("p4", NOW, "blocked", "quiet_hours"),
            Outcome("p5", NOW, "blocked", "pressure_budget"),
        ]
        rep = aggregate(outs, window_days=90, trigger_type="state",
                        names={"p1": "Maya"}, notes=["note"])
        assert rep.fires == 5
        assert rep.actions["would_send"] == 2
        assert rep.blocked == 3
        assert rep.blocked_by == {"pressure_budget": 2, "quiet_hours": 1}

    def test_sample_puts_blocked_first(self):
        outs = [Outcome("p1", NOW, "would_send"),
                Outcome("p2", NOW, "blocked", "quiet_hours")]
        rep = aggregate(outs, window_days=90, trigger_type="event",
                        names={"p2": "Daniel"}, notes=[])
        assert rep.sample[0]["outcome"] == "blocked"
        assert rep.sample[0]["person_name"] == "Daniel"


class TestSimulateFlowIO:
    def test_event_flow_end_to_end(self, monkeypatch):
        # Two historical booking_canceled interactions → 2 notifies.
        monkeypatch.setattr(simulate.flow_policy, "pressure_budget", lambda: 2)
        conn = FakeConn(
            fetchall_queue=[
                [("p1", NOW - datetime.timedelta(days=3)),
                 ("p2", NOW - datetime.timedelta(days=10))],   # _fetch_event_rows
                [("p1", "Maya"), ("p2", "Daniel")],            # _fetch_names
            ],
        )
        report = simulate.simulate_flow(
            conn, trigger={"type": "event", "kind": "booking_canceled"},
            graph=NOTIFY_GRAPH, now=NOW,
        )
        assert report["fires"] == 2
        assert report["actions"]["would_notify"] == 2
        assert report["trigger_type"] == "event"
        assert report["blocked"] == 0

    def test_unknown_trigger_type_is_safe(self):
        conn = FakeConn()
        report = simulate.simulate_flow(conn, trigger={"type": "manual"}, graph=NOTIFY_GRAPH, now=NOW)
        assert report["fires"] == 0
        assert "Unknown trigger" in report["notes"][0]

    def test_invalid_state_predicate_returns_a_note_not_a_crash(self):
        conn = FakeConn()
        report = simulate.simulate_flow(
            conn, trigger={"type": "state", "predicate": {"field": "bogus", "op": "eq", "value": 1}},
            graph=NOTIFY_GRAPH, now=NOW,
        )
        assert report["fires"] == 0
        assert "Invalid predicate" in report["notes"][0]


class TestUuidArrayCasts:
    """Regression for the `operator does not exist: uuid = text` crash: the
    pure core str()-ifies every person_id, so any query that feeds those ids
    into `= ANY(%s)` against a uuid column MUST cast to `::uuid[]`, or psycopg2
    adapts the Python str list to a text[] literal and Postgres rejects it.

    The DB is mocked in CI (a fake cursor never type-checks SQL), so these lock
    in the cast by inspecting the emitted SQL — across BOTH trigger families,
    since both reach _fetch_names on the person-name lookup.
    """

    def _names_query(self, conn) -> str:
        matches = [s for s, _ in conn.executed if "FROM person" in s]
        assert matches, "expected a person-name lookup to run"
        return matches[0]

    @pytest.mark.parametrize("kind", ["booking_canceled", "captured", "outreach_click"])
    def test_event_trigger_person_lookup_casts_uuid_array(self, monkeypatch, kind):
        monkeypatch.setattr(simulate.flow_policy, "pressure_budget", lambda: 2)
        conn = FakeConn(
            fetchall_queue=[
                [("11111111-1111-1111-1111-111111111111", NOW - datetime.timedelta(days=2)),
                 ("22222222-2222-2222-2222-222222222222", NOW - datetime.timedelta(days=9))],  # _fetch_event_rows
                [("11111111-1111-1111-1111-111111111111", "Maya"),
                 ("22222222-2222-2222-2222-222222222222", "Daniel")],                          # _fetch_names
            ],
        )
        report = simulate.simulate_flow(
            conn, trigger={"type": "event", "kind": kind}, graph=NOTIFY_GRAPH, now=NOW,
        )
        assert report["fires"] == 2
        assert "ANY(%s::uuid[])" in self._names_query(conn)

    def test_state_trigger_person_lookup_casts_uuid_array(self, monkeypatch):
        monkeypatch.setattr(simulate.flow_policy, "pressure_budget", lambda: 2)
        entered = NOW - datetime.timedelta(days=40)
        conn = FakeConn(
            fetchall_queue=[
                # _fetch_timelines: one person entered 'qualified' then went quiet.
                [("33333333-3333-3333-3333-333333333333", entered, "stage_change", {"to": "qualified"})],
                # _crisis_as_of (no crisis) then _automated_sends_before are fetchone;
                # _fetch_names returns the display name.
                [("33333333-3333-3333-3333-333333333333", "Noa")],
            ],
            fetchone_queue=[None, (0,)],  # crisis lookup miss, 0 prior automated sends
        )
        report = simulate.simulate_flow(
            conn, trigger={"type": "state", "predicate": COOLING_PREDICATE},
            graph=SEND_GRAPH, now=NOW,
        )
        assert report["fires"] == 1
        assert "ANY(%s::uuid[])" in self._names_query(conn)
