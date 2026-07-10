"""
tests.test_nexus_flows_runner — the graph walk executor. Pattern B (FakeConn).

_drive() is exercised via run_sweep() (the public entry) so tests also cover
claiming + timer resumption, not just node execution in isolation.
"""
import datetime

import pytest

from nexus.flows import policy as flow_policy
from nexus.flows import runner
from tests._flows_fakes import FakeConn


@pytest.fixture(autouse=True)
def _flows_on(monkeypatch):
    monkeypatch.setattr(flow_policy, "flows_enabled", lambda: True)


def _run_row(id_, flow_id, person_id, cursor_node, context, slug, live, graph):
    return (id_, flow_id, person_id, cursor_node, context, slug, live, graph)


# A single-node graph: trigger -> notify_operator, no condition/branch.
NOTIFY_GRAPH = {
    "nodes": [
        {"id": "t1", "type": "trigger"},
        {"id": "n1", "type": "action:notify_operator", "body": "check on this lead"},
    ],
    "edges": [{"from": "t1", "to": "n1"}],
}


class TestRunSweepGate:
    def test_disabled_engine_never_claims(self, monkeypatch):
        monkeypatch.setattr(flow_policy, "flows_enabled", lambda: False)
        conn = FakeConn()
        summary = runner.run_sweep(conn)
        assert summary["claimed"] == 0
        assert conn.executed == []


class TestShadowMode:
    def test_notify_operator_shadow_when_not_live(self):
        conn = FakeConn(
            fetchall_queue=[
                [],   # flow_timers fired -> none
                [_run_row("r1", "f1", "p1", None, {}, "cooling-lead-nudge", False, NOTIFY_GRAPH)],  # claim
                [],   # signals_for -> open_opportunity_signals (no open opp)
            ],
        )
        summary = runner.run_sweep(conn)
        assert summary["success"] == 1

        step_stmts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO flow_run_steps")]
        assert len(step_stmts) == 2   # trigger + notify_operator
        notify_step = step_stmts[1]
        assert notify_step[1][3] == "shadow"   # status column
        assert '"would_notify"' in notify_step[1][5]   # output JSON contains the preview

        complete_stmts = [s for s, _ in conn.executed if s.startswith("UPDATE flow_runs SET status = 'success'")]
        assert len(complete_stmts) == 1

    def test_send_message_shadow_never_calls_real_send(self, monkeypatch):
        called = {"sent": False}
        monkeypatch.setattr(flow_policy, "guarded_whatsapp_send",
                            lambda *a, **k: called.__setitem__("sent", True))
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "n1", "type": "action:send_message", "body": "hi"},
            ],
            "edges": [{"from": "t1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        runner.run_sweep(conn)
        assert called["sent"] is False


class TestLiveSendMessage:
    def test_live_flow_calls_guarded_send_and_records_success(self, monkeypatch):
        outcome = flow_policy.SendOutcome(sent=True, verdict=flow_policy.PolicyVerdict(True),
                                          provider_message_id="wamid.1")
        monkeypatch.setattr(flow_policy, "guarded_whatsapp_send", lambda *a, **k: outcome)
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "n1", "type": "action:send_message", "body": "hi"},
            ],
            "edges": [{"from": "t1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", True, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["success"] == 1
        step_stmts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO flow_run_steps")]
        assert step_stmts[1][1][3] == "success"

    def test_live_flow_records_blocked_when_policy_vetoes(self, monkeypatch):
        outcome = flow_policy.SendOutcome(
            sent=False, verdict=flow_policy.PolicyVerdict(False, "quiet_hours", "21:00-09:00"),
        )
        monkeypatch.setattr(flow_policy, "guarded_whatsapp_send", lambda *a, **k: outcome)
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "n1", "type": "action:send_message", "body": "hi"},
            ],
            "edges": [{"from": "t1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", True, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["success"] == 1   # the RUN completes; the STEP is 'blocked'
        step_stmts = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO flow_run_steps")]
        assert step_stmts[1][1][3] == "blocked"


class TestCondition:
    def test_true_branch_taken(self):
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "c1", "type": "condition",
                 "predicate": {"field": "stage", "op": "eq", "value": "qualified"}},
                {"id": "n_true", "type": "action:add_note", "note": "took true branch"},
                {"id": "n_false", "type": "action:add_note", "note": "took false branch"},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "n_true", "when": "true"},
                {"from": "c1", "to": "n_false", "when": "false"},
            ],
        }
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        conn = FakeConn(
            fetchall_queue=[
                [],   # timers
                [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)],   # claim
                [("p1", "o1", "qualified", entered, "whatsapp", 40.0, 12.0)],   # signals_for
            ],
        )
        runner.run_sweep(conn)
        note_stmts = [(s, p) for s, p in conn.executed if "INSERT INTO interactions" in s]
        assert len(note_stmts) == 1
        payload_json = note_stmts[0][1][4]   # log_interaction's payload param (JSON string)
        assert "took true branch" in payload_json
        assert "took false branch" not in payload_json

    def test_no_edge_for_branch_ends_run_cleanly(self):
        """A condition with no 'false' edge is a valid, intentional graph
        shape (the seeded flows are single-branch) — the run must complete,
        not fail."""
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "c1", "type": "condition",
                 "predicate": {"field": "stage", "op": "eq", "value": "qualified"}},
                {"id": "n_true", "type": "action:add_note", "note": "x"},
            ],
            "edges": [
                {"from": "t1", "to": "c1"},
                {"from": "c1", "to": "n_true", "when": "true"},
            ],
        }
        entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
        conn = FakeConn(
            fetchall_queue=[
                [],
                [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)],
                [("p1", "o1", "engaged", entered, "whatsapp", 1.0, 1.0)],   # stage != qualified -> false
            ],
        )
        summary = runner.run_sweep(conn)
        assert summary["success"] == 1
        assert not any("INSERT INTO interactions" in s for s, _ in conn.executed)


class TestWait:
    def test_wait_parks_the_run_and_inserts_a_timer(self):
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "w1", "type": "wait", "hours": 24},
                {"id": "n1", "type": "action:add_note", "note": "after the wait"},
            ],
            "edges": [{"from": "t1", "to": "w1"}, {"from": "w1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["waiting"] == 1
        timer_stmts = [s for s, _ in conn.executed if s.startswith("INSERT INTO flow_timers")]
        assert len(timer_stmts) == 1
        parked_stmts = [s for s, _ in conn.executed if s.startswith("UPDATE flow_runs SET status = 'waiting'")]
        assert len(parked_stmts) == 1
        # the note AFTER the wait must not have run yet
        assert not any("INSERT INTO interactions" in s for s, _ in conn.executed)

    def test_fired_timer_flips_run_back_to_running_and_resumes(self):
        graph = {
            "nodes": [
                {"id": "w1", "type": "wait", "hours": 24},
                {"id": "n1", "type": "action:add_note", "note": "resumed"},
            ],
            "edges": [{"from": "w1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[
                [("run-1",)],   # fired timers -> RETURNING flow_run_id
                # cursor_node='n1' — _park_waiting saves the node AFTER the
                # wait (regression test: it must never re-save 'w1' itself,
                # or resumption would re-execute the wait and park forever).
                [_run_row("run-1", "f1", "p1", "n1",
                         {"signals": {"stage": "qualified"}, "opportunity_id": "o1"},
                         "x", False, graph)],
            ],
        )
        summary = runner.run_sweep(conn)
        assert summary["resumed"] == 1
        assert summary["success"] == 1
        resume_stmts = [s for s, _ in conn.executed if "flow_timers SET fired = TRUE" in s]
        assert len(resume_stmts) == 1
        reactivate_stmts = [s for s, _ in conn.executed if "flow_runs SET status = 'running' WHERE id = ANY" in s]
        assert len(reactivate_stmts) == 1
        note_stmts = [s for s, _ in conn.executed if "INSERT INTO interactions" in s]
        assert len(note_stmts) == 1   # the post-wait node actually ran

    def test_park_waiting_saves_the_node_after_the_wait_not_the_wait_itself(self):
        """Direct regression test for the bug above, exercised via a single
        drive pass (not a resume) so the UPDATE's saved cursor_node is
        asserted directly."""
        graph = {
            "nodes": [
                {"id": "t1", "type": "trigger"},
                {"id": "w1", "type": "wait", "hours": 24},
                {"id": "n1", "type": "action:add_note", "note": "after"},
            ],
            "edges": [{"from": "t1", "to": "w1"}, {"from": "w1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        runner.run_sweep(conn)
        park_stmts = [(s, p) for s, p in conn.executed if s.startswith("UPDATE flow_runs SET status = 'waiting'")]
        assert len(park_stmts) == 1
        assert park_stmts[0][1][0] == "n1"   # cursor_node param — NOT 'w1'


class TestAdvanceStage:
    def test_advances_when_opportunity_id_in_context(self, monkeypatch):
        monkeypatch.setattr(runner.nexus_interactions, "advance_stage", lambda *a, **k: True)
        graph = {
            "nodes": [{"id": "t1", "type": "trigger"},
                     {"id": "n1", "type": "action:advance_stage", "to_stage": "qualified"}],
            "edges": [{"from": "t1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {"opportunity_id": "o1"}, "x", False, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["success"] == 1

    def test_fails_cleanly_without_opportunity_id(self):
        graph = {
            "nodes": [{"id": "t1", "type": "trigger"},
                     {"id": "n1", "type": "action:advance_stage", "to_stage": "qualified"}],
            "edges": [{"from": "t1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["failed"] == 1
        fail_stmts = [s for s, _ in conn.executed if s.startswith("UPDATE flow_runs SET status = 'failed'")]
        assert len(fail_stmts) == 1


class TestMalformedGraph:
    def test_unknown_node_id_fails_the_run_not_the_sweep(self):
        graph = {
            "nodes": [{"id": "t1", "type": "trigger"}],
            "edges": [{"from": "t1", "to": "ghost"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["failed"] == 1

    def test_unregistered_node_type_fails_cleanly(self):
        graph = {
            "nodes": [{"id": "t1", "type": "trigger"}, {"id": "n1", "type": "action:launch_missiles"}],
            "edges": [{"from": "t1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["failed"] == 1

    def test_step_budget_exhaustion_parks_as_continuing_not_failed(self):
        # A trivial cycle: t1 -> n1 -> n1 -> n1 ... forever.
        graph = {
            "nodes": [{"id": "t1", "type": "trigger"}, {"id": "n1", "type": "action:add_note", "note": "loop"}],
            "edges": [{"from": "t1", "to": "n1"}, {"from": "n1", "to": "n1"}],
        }
        conn = FakeConn(
            fetchall_queue=[[], [_run_row("r1", "f1", "p1", None, {}, "x", False, graph)], []],
        )
        summary = runner.run_sweep(conn)
        assert summary["continuing"] == 1
        # still 'running' — no success/failed/waiting transition fired
        assert not any(
            s.startswith("UPDATE flow_runs SET status = 'success'")
            or s.startswith("UPDATE flow_runs SET status = 'failed'")
            or s.startswith("UPDATE flow_runs SET status = 'waiting'")
            for s, _ in conn.executed
        )
