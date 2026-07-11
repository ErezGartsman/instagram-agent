"""
tests.test_flows_endpoints — routers/flows.py HTTP contract. DB mocked, no
network. Pattern C (TestClient + MagicMock + dependency override), matching
test_cockpit_action.py / test_one_thread_send.py house style exactly.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app


@pytest.fixture
def client():
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


def _conn_with(fetchone=None, fetchall=None):
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall or []
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value = cur
    return MagicMock(return_value=conn)


class TestListFlows:
    def test_requires_cockpit_auth(self):
        # A raw client with no dependency override — the real auth gate applies.
        r = TestClient(app).get("/api/cockpit/flows")
        assert r.status_code in (401, 503)   # 503 if supabase_jwt_secret unset in CI

    def test_success_shape(self, client, monkeypatch):
        monkeypatch.setattr(main.nexus_flows_policy, "flows_enabled", lambda: False)
        graph = {"nodes": [{"id": "t1", "type": "trigger"}], "edges": []}
        row = (
            "f1", "cooling-lead-nudge", 1, "published", False,
            "Cooling lead → notify operator", "desc",
            {"type": "state", "predicate": {}}, None, None, graph, 3, None,
        )
        with patch.object(main, "get_db_conn", _conn_with(fetchall=[row])):
            r = client.get("/api/cockpit/flows")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["enabled"] is False
        assert len(body["flows"]) == 1
        assert body["flows"][0]["slug"] == "cooling-lead-nudge"
        assert body["flows"][0]["live"] is False
        assert body["flows"][0]["run_count"] == 3
        assert body["flows"][0]["graph"] == graph

    def test_db_error_returns_error_shape_not_500(self, client):
        broken = MagicMock(side_effect=RuntimeError("db down"))
        with patch.object(main, "get_db_conn", broken):
            r = client.get("/api/cockpit/flows")
        assert r.status_code == 200   # the endpoint's own contract: never a bare 500
        body = r.json()
        assert body["status"] == "error"
        assert body["flows"] == []


class TestListFlowRuns:
    def test_success_shape_with_steps(self, client):
        run_row = ("r1", "p1", "Dana K.", "success", None, None, None)
        step_row = ("r1", "n1", "action:notify_operator", "shadow",
                    {"would_notify": "check on this lead"}, None, None)
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.__exit__.return_value = False
        cur.fetchall.side_effect = [[run_row], [step_row]]
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = False
        conn.cursor.return_value = cur

        with patch.object(main, "get_db_conn", MagicMock(return_value=conn)):
            r = client.get("/api/cockpit/flows/f1/runs")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert len(body["runs"]) == 1
        assert body["runs"][0]["status"] == "success"
        assert len(body["runs"][0]["steps"]) == 1
        assert body["runs"][0]["steps"][0]["status"] == "shadow"


class TestTriggerSweep:
    def test_success_aggregates_all_three_phases(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_events", return_value=2), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_states", return_value=1), \
             patch.object(main.nexus_flows_runner, "run_sweep",
                          return_value={"claimed": 3, "success": 2, "waiting": 1}):
            r = client.post("/api/cockpit/flows/sweep")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["events_dispatched"] == 2
        assert body["states_dispatched"] == 1
        assert body["run"]["claimed"] == 3

    def test_exception_is_reported_not_500(self, client):
        with patch.object(main, "get_db_conn", MagicMock(side_effect=RuntimeError("boom"))):
            r = client.post("/api/cockpit/flows/sweep")
        assert r.status_code == 200
        assert r.json()["status"] == "error"


class TestCronFlowsSweep:
    def test_rejects_bad_secret(self, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "s3cr3t")
        r = TestClient(app).post("/api/cron/flows-sweep", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_accepts_correct_bearer_secret(self, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "s3cr3t")
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_events", return_value=0), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_states", return_value=0), \
             patch.object(main.nexus_flows_runner, "run_sweep", return_value={"claimed": 0}):
            r = TestClient(app).post("/api/cron/flows-sweep",
                                     headers={"Authorization": "Bearer s3cr3t"})
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_accepts_x_cron_secret_header(self, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "s3cr3t")
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_events", return_value=0), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_states", return_value=0), \
             patch.object(main.nexus_flows_runner, "run_sweep", return_value={"claimed": 0}):
            r = TestClient(app).post("/api/cron/flows-sweep",
                                     headers={"X-Cron-Secret": "s3cr3t"})
        assert r.status_code == 200

    def test_fails_closed_on_vercel_when_secret_unset(self, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "")
        monkeypatch.setenv("VERCEL", "1")
        r = TestClient(app).post("/api/cron/flows-sweep")
        assert r.status_code == 503

    def test_dev_mode_skips_guard_when_secret_unset_and_not_vercel(self, monkeypatch):
        monkeypatch.setattr(main.settings, "cron_secret", "")
        monkeypatch.delenv("VERCEL", raising=False)
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_events", return_value=0), \
             patch.object(main.nexus_flows_dispatcher, "dispatch_states", return_value=0), \
             patch.object(main.nexus_flows_runner, "run_sweep", return_value={"claimed": 0}):
            r = TestClient(app).post("/api/cron/flows-sweep")
        assert r.status_code == 200


# ── F3 authoring endpoints ────────────────────────────────────────────────────

from nexus.flows.authoring import AuthoringError  # noqa: E402


class TestCreateFlow:
    def test_success_returns_id(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "create_draft", return_value="new-flow-id"):
            r = client.post("/api/cockpit/flows", json={
                "name": "My Flow", "trigger": {"type": "event", "kind": "booking_canceled"},
                "graph": {"nodes": [{"id": "t1", "type": "trigger"}], "edges": []},
            })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success" and body["id"] == "new-flow-id"

    def test_validation_error_is_422(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "create_draft",
                          side_effect=AuthoringError("a flow must have exactly one trigger node")):
            r = client.post("/api/cockpit/flows", json={"name": "x", "trigger": {}, "graph": {}})
        assert r.status_code == 422
        assert "exactly one trigger" in r.json()["detail"]


class TestUpdateFlow:
    def test_success(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "update_draft") as upd:
            r = client.patch("/api/cockpit/flows/f1", json={"name": "Renamed"})
        assert r.status_code == 200 and r.json()["status"] == "success"
        assert upd.called

    def test_editing_published_is_422(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "update_draft",
                          side_effect=AuthoringError("a published flow is immutable — fork a new draft to edit it")):
            r = client.patch("/api/cockpit/flows/f1", json={"name": "x"})
        assert r.status_code == 422
        assert "immutable" in r.json()["detail"]


class TestSimulateEndpoint:
    def test_returns_report(self, client):
        report = {"fires": 34, "actions": {"would_notify": 34}, "blocked": 6,
                  "blocked_by": {"pressure_budget": 4, "quiet_hours": 2}, "window_days": 90}
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "load_flow",
                          return_value={"trigger": {"type": "event", "kind": "x"}, "graph": {"nodes": [], "edges": []}}), \
             patch.object(main.nexus_flows_simulate, "simulate_flow", return_value=report):
            r = client.post("/api/cockpit/flows/f1/simulate", json={})
        assert r.status_code == 200
        assert r.json()["report"]["fires"] == 34

    def test_missing_flow_is_404(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "load_flow", return_value=None):
            r = client.post("/api/cockpit/flows/ghost/simulate", json={})
        assert r.status_code == 404


class TestPublishEndpoint:
    def test_runs_sim_then_publishes(self, client):
        report = {"fires": 12, "blocked": 0}
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "load_flow",
                          return_value={"trigger": {"type": "event", "kind": "x"}, "graph": {"nodes": [], "edges": []}}), \
             patch.object(main.nexus_flows_simulate, "simulate_flow", return_value=report), \
             patch.object(main.nexus_flows_authoring, "publish") as pub:
            r = client.post("/api/cockpit/flows/f1/publish")
        assert r.status_code == 200
        assert r.json()["report"]["fires"] == 12
        # publish was gated on the simulation report just produced
        assert pub.call_args.kwargs["simulation"] == report

    def test_publish_of_nondraft_is_422(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "load_flow",
                          return_value={"trigger": {"type": "event", "kind": "x"}, "graph": {"nodes": [], "edges": []}}), \
             patch.object(main.nexus_flows_simulate, "simulate_flow", return_value={"fires": 1}), \
             patch.object(main.nexus_flows_authoring, "publish",
                          side_effect=AuthoringError("only a draft can be published (this is published)")):
            r = client.post("/api/cockpit/flows/f1/publish")
        assert r.status_code == 422


class TestStatusEndpoint:
    def test_pause(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "set_status", return_value="paused"):
            r = client.post("/api/cockpit/flows/f1/status", json={"action": "pause"})
        assert r.status_code == 200 and r.json()["flow_status"] == "paused"

    def test_illegal_transition_is_422(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_authoring, "set_status",
                          side_effect=AuthoringError("cannot pause a draft flow")):
            r = client.post("/api/cockpit/flows/f1/status", json={"action": "pause"})
        assert r.status_code == 422


class TestFlowSettings:
    def test_updates_budget_and_returns_effective(self, client):
        with patch.object(main, "get_db_conn", _conn_with()), \
             patch.object(main.nexus_flows_policy, "flows_enabled", return_value=True), \
             patch.object(main.nexus_flows_policy, "pressure_budget", return_value=3):
            r = client.patch("/api/cockpit/flow-settings", json={"enabled": True, "pressure_budget": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True and body["pressure_budget"] == 3

    def test_bad_budget_is_422(self, client):
        with patch.object(main, "get_db_conn", _conn_with()):
            r = client.patch("/api/cockpit/flow-settings", json={"pressure_budget": "lots"})
        assert r.status_code == 422
