"""
tests.test_nexus_flows_signals — the live-state snapshot shared by the
state-trigger dispatcher and condition-node evaluation. Pattern B (FakeConn).
"""
import datetime

from nexus.flows import signals as flow_signals
from tests._flows_fakes import FakeConn


def _row(person_id, opp_id, stage, stage_entered_at, channel, hours_since_last, hours_in_stage):
    return (person_id, opp_id, stage, stage_entered_at, channel, hours_since_last, hours_in_stage)


class TestOpenOpportunitySignals:
    def test_yields_one_tuple_per_open_opportunity(self):
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        conn = FakeConn(fetchall_queue=[[
            _row("p1", "o1", "qualified", entered, "whatsapp", 40.0, 12.0),
            _row("p2", "o2", "engaged", entered, "telegram", None, 3.0),
        ]])
        results = list(flow_signals.open_opportunity_signals(conn))
        assert len(results) == 2

        person_id, opp_id, stage_entered_at, sig = results[0]
        assert person_id == "p1"
        assert opp_id == "o1"
        assert stage_entered_at == entered
        assert sig == {
            "stage": "qualified", "hours_since_last": 40.0, "hours_in_stage": 12.0,
            "channel": "whatsapp", "urgency": None, "waiting_on": None,
        }

    def test_none_hours_pass_through_as_none_not_zero(self):
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        conn = FakeConn(fetchall_queue=[[
            _row("p1", "o1", "engaged", entered, "instagram", None, None),
        ]])
        _, _, _, sig = next(flow_signals.open_opportunity_signals(conn))
        assert sig["hours_since_last"] is None
        assert sig["hours_in_stage"] is None

    def test_empty_result_yields_nothing(self):
        conn = FakeConn(fetchall_queue=[[]])
        assert list(flow_signals.open_opportunity_signals(conn)) == []


class TestSignalsFor:
    def test_finds_matching_person(self):
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        conn = FakeConn(fetchall_queue=[[
            _row("p1", "o1", "qualified", entered, "whatsapp", 40.0, 12.0),
            _row("p2", "o2", "engaged", entered, "telegram", 1.0, 1.0),
        ]])
        sig = flow_signals.signals_for(conn, "p2")
        assert sig["stage"] == "engaged"
        assert sig["opportunity_id"] == "o2"

    def test_returns_none_when_person_has_no_open_opportunity(self):
        conn = FakeConn(fetchall_queue=[[]])
        assert flow_signals.signals_for(conn, "ghost") is None
