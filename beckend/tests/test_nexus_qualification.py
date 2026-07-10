"""
tests.test_nexus_qualification — the F1 retrofit: qualification_agent's
WhatsApp send now routes through nexus.flows.policy.guarded_whatsapp_send
instead of composing the outbound_messages insert / 'contacted' log itself.
Pattern B (FakeConn), guarded_whatsapp_send mocked at the module boundary
(the Policy Gate's own behavior is covered by test_nexus_flows_policy.py).
"""
from nexus.agents import qualification
from nexus.flows import policy as flow_policy
from tests._flows_fakes import FakeConn


def _person_row(name="Dana", goal=None, tension=None):
    return (name, "BR-1234", {"goal": goal, "tension": tension}, None)


def _opp_row(opp_id="o1", stage="engaged", channel="whatsapp"):
    return (opp_id, stage, channel)


class TestAdvancePath:
    def test_advances_when_goal_and_tension_present(self, monkeypatch):
        monkeypatch.setattr(qualification.nexus_interactions, "advance_stage", lambda *a, **k: True)
        conn = FakeConn(fetchone_queue=[
            _person_row(goal="find peace", tension="conflict avoidance"),
            _opp_row(),
        ])
        result = qualification.qualification_agent(conn, "p1", "run1")
        assert result.status == "success"
        assert result.output["new_stage"] == "qualified"


class TestRequestPathViaPolicyGate:
    def test_success_persists_info_request_and_uses_gate_message_id(self, monkeypatch):
        outcome = flow_policy.SendOutcome(
            sent=True, verdict=flow_policy.PolicyVerdict(True), provider_message_id="wamid.xyz",
        )
        called = {}
        monkeypatch.setattr(
            flow_policy, "guarded_whatsapp_send",
            lambda conn, **kw: (called.update(kw) or outcome),
        )
        conn = FakeConn(fetchone_queue=[
            _person_row(goal=None, tension=None),   # both missing
            _opp_row(),
            None,   # _has_recent_info_request -> no recent request
        ])
        result = qualification.qualification_agent(conn, "p1", "run1")

        assert result.status == "success"
        assert called["source"] == "agent:qualification"
        assert called["person_id"] == "p1"
        assert called["opportunity_id"] == "o1"
        info_request_stmts = [s for s, _ in conn.executed if s.startswith("INSERT INTO info_requests")]
        assert len(info_request_stmts) == 1
        # No duplicate outbound_messages/interactions writes — the gate owns those now.
        assert not any(s.startswith("INSERT INTO outbound_messages") for s, _ in conn.executed)
        assert not any("INSERT INTO interactions" in s for s, _ in conn.executed)

    def test_policy_veto_is_skipped_not_failed(self, monkeypatch):
        outcome = flow_policy.SendOutcome(
            sent=False, verdict=flow_policy.PolicyVerdict(False, "pressure_budget", "2/2 in 7d"),
        )
        monkeypatch.setattr(flow_policy, "guarded_whatsapp_send", lambda conn, **kw: outcome)
        conn = FakeConn(fetchone_queue=[
            _person_row(goal=None, tension=None),
            _opp_row(),
            None,
        ])
        result = qualification.qualification_agent(conn, "p1", "run1")
        assert result.status == "skipped"
        assert result.output["reason"] == "pressure_budget"
        assert not any(s.startswith("INSERT INTO info_requests") for s, _ in conn.executed)

    def test_send_failure_is_a_real_failure(self, monkeypatch):
        outcome = flow_policy.SendOutcome(
            sent=False, verdict=flow_policy.PolicyVerdict(False, "send_failed", "no response"),
        )
        monkeypatch.setattr(flow_policy, "guarded_whatsapp_send", lambda conn, **kw: outcome)
        conn = FakeConn(fetchone_queue=[
            _person_row(goal=None, tension=None),
            _opp_row(),
            None,
        ])
        result = qualification.qualification_agent(conn, "p1", "run1")
        assert result.status == "failed"
        assert result.error is not None

    def test_no_whatsapp_number_is_skipped(self, monkeypatch):
        outcome = flow_policy.SendOutcome(
            sent=False, verdict=flow_policy.PolicyVerdict(False, "no_whatsapp_number", "no reachable identity"),
        )
        monkeypatch.setattr(flow_policy, "guarded_whatsapp_send", lambda conn, **kw: outcome)
        conn = FakeConn(fetchone_queue=[
            _person_row(goal=None, tension=None),
            _opp_row(),
            None,
        ])
        result = qualification.qualification_agent(conn, "p1", "run1")
        assert result.status == "skipped"
        assert result.output["reason"] == "no_whatsapp_number"
