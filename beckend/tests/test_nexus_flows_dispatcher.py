"""
tests.test_nexus_flows_dispatcher — event/state trigger -> flow_runs. Pattern
B (FakeConn). flows.enabled is forced on via monkeypatching
nexus.flows.policy.flows_enabled directly (dispatcher's own kill-switch
check) so these tests exercise dispatch logic, not the config bridge.
"""
import datetime

import pytest

from nexus.flows import dispatcher
from nexus.flows import policy as flow_policy
from tests._flows_fakes import FakeConn


@pytest.fixture(autouse=True)
def _flows_on(monkeypatch):
    monkeypatch.setattr(flow_policy, "flows_enabled", lambda: True)


def _flow_row(id_, slug, live, trigger, graph=None):
    return (id_, slug, live, trigger, graph or {"nodes": [], "edges": []})


# rowcount is consumed by EVERY execute() call in FIFO order (see
# tests/_flows_fakes.py), not just the ones a test cares about. dispatch_events
# issues three SELECTs before it ever reaches a flow_runs INSERT:
# _published_flows, _get_watermark, the interactions query — pad with three
# unchecked dummy values, then append the real value(s) under test.
_LEADING_EVENT_SELECTS = [1, 1, 1]


class TestDispatchEventsGate:
    def test_disabled_flows_engine_short_circuits(self, monkeypatch):
        monkeypatch.setattr(flow_policy, "flows_enabled", lambda: False)
        conn = FakeConn()
        assert dispatcher.dispatch_events(conn) == 0
        assert conn.executed == []   # never even queried published flows

    def test_no_published_event_flows_short_circuits(self):
        conn = FakeConn(fetchall_queue=[[]])   # _published_flows -> none
        assert dispatcher.dispatch_events(conn) == 0


class TestDispatchEvents:
    def test_matching_interaction_inserts_a_run(self):
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "booking-canceled-reengage", False,
                          {"type": "event", "kind": "booking_canceled"})],   # _published_flows
                [(101, "p1", "booking_canceled", {})],                       # interactions since watermark
            ],
            fetchone_queue=[None],   # _get_watermark -> app_config row absent
            rowcount_queue=[*_LEADING_EVENT_SELECTS, 1],   # the flow_runs INSERT
        )
        inserted = dispatcher.dispatch_events(conn)
        assert inserted == 1
        insert_stmts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO flow_runs")]
        assert len(insert_stmts) == 1
        assert insert_stmts[0][1][-1] == "event:f1:101"   # dedup_key is last param

    def test_non_matching_kind_is_skipped(self):
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "booking-canceled-reengage", False,
                          {"type": "event", "kind": "booking_canceled"})],
                [(101, "p1", "outreach_click", {})],
            ],
            fetchone_queue=[None],
        )
        assert dispatcher.dispatch_events(conn) == 0
        assert not any(s.startswith("INSERT INTO flow_runs") for s, _ in conn.executed)

    def test_watermark_advances_to_max_interaction_id(self):
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "x", False, {"type": "event", "kind": "booking_canceled"})],
                [(101, "p1", "booking_canceled", {}), (105, "p2", "booking_canceled", {})],
            ],
            fetchone_queue=[("50",)],   # existing watermark
            rowcount_queue=[*_LEADING_EVENT_SELECTS, 1, 1],   # the two flow_runs INSERTs
        )
        dispatcher.dispatch_events(conn)
        watermark_stmts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO app_config")]
        assert len(watermark_stmts) == 1
        assert watermark_stmts[0][1][1] == "105"   # advanced to the max id seen

    def test_causation_depth_at_ceiling_is_never_dispatched(self):
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "x", False, {"type": "event", "kind": "booking_canceled"})],
                [(101, "p1", "booking_canceled", {"caused_by_flow_depth": 2})],
            ],
            fetchone_queue=[None],
        )
        assert dispatcher.dispatch_events(conn) == 0
        assert not any(s.startswith("INSERT INTO flow_runs") for s, _ in conn.executed)

    def test_dedup_conflict_does_not_count_as_inserted(self):
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "x", False, {"type": "event", "kind": "booking_canceled"})],
                [(101, "p1", "booking_canceled", {})],
            ],
            fetchone_queue=[None],
            # ON CONFLICT DO NOTHING on the flow_runs INSERT -> rowcount 0.
            rowcount_queue=[*_LEADING_EVENT_SELECTS, 0],
        )
        assert dispatcher.dispatch_events(conn) == 0


class TestDispatchStates:
    def test_matching_signal_inserts_a_run(self):
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        predicate = {"all": [
            {"field": "stage", "op": "in", "value": ["qualified", "captured", "briefed"]},
            {"field": "hours_since_last", "op": "gte", "value": 36},
        ]}
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "cooling-lead-nudge", False, {"type": "state", "predicate": predicate})],
                [("p1", "o1", "qualified", entered, "whatsapp", 40.0, 12.0)],   # open_opportunity_signals
            ],
            # [0]=_published_flows SELECT, [1]=open_opportunity_signals SELECT
            # (both unchecked), [2]=the flow_runs INSERT under test.
            rowcount_queue=[1, 1, 1],
        )
        inserted = dispatcher.dispatch_states(conn)
        assert inserted == 1
        insert_stmts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO flow_runs")]
        assert insert_stmts[0][1][-1] == f"state:f1:p1:{entered.isoformat()}"

    def test_non_matching_signal_is_skipped(self):
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        predicate = {"field": "hours_since_last", "op": "gte", "value": 36}
        conn = FakeConn(
            fetchall_queue=[
                [_flow_row("f1", "x", False, {"type": "state", "predicate": predicate})],
                [("p1", "o1", "engaged", entered, "whatsapp", 3.0, 3.0)],
            ],
        )
        assert dispatcher.dispatch_states(conn) == 0

    def test_missing_predicate_is_skipped_not_crashed(self):
        conn = FakeConn(fetchall_queue=[
            [_flow_row("f1", "x", False, {"type": "state"})],   # no predicate key
        ])
        assert dispatcher.dispatch_states(conn) == 0

    def test_invalid_predicate_is_skipped_not_crashed(self):
        conn = FakeConn(fetchall_queue=[
            [_flow_row("f1", "x", False, {"type": "state", "predicate": {"field": "bogus", "op": "eq", "value": 1}})],
        ])
        assert dispatcher.dispatch_states(conn) == 0
