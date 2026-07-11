"""
tests.test_nexus_flows_authoring — validation (pure) + the mutation state
machine (FakeConn). The publish gate's simulation is injected, so this file
tests the AUTHORING contract (immutability, versioning, one-published-per-slug)
independent of the simulation engine.
"""
import pytest

from nexus.flows import authoring
from nexus.flows.authoring import AuthoringError
from tests._flows_fakes import FakeConn

GOOD_GRAPH = {
    "nodes": [{"id": "t1", "type": "trigger"},
              {"id": "n1", "type": "action:notify_operator", "body": "hi"}],
    "edges": [{"from": "t1", "to": "n1"}],
}
EVENT_TRIGGER = {"type": "event", "kind": "booking_canceled"}
STATE_TRIGGER = {"type": "state", "predicate": {"field": "stage", "op": "eq", "value": "qualified"}}


class TestValidateGraph:
    def test_accepts_a_good_graph(self):
        authoring.validate_graph(GOOD_GRAPH)  # no raise

    def test_requires_exactly_one_trigger(self):
        with pytest.raises(AuthoringError, match="exactly one trigger"):
            authoring.validate_graph({"nodes": [{"id": "n1", "type": "action:add_note"}], "edges": []})
        with pytest.raises(AuthoringError, match="exactly one trigger"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"}, {"id": "t2", "type": "trigger"}],
                "edges": [],
            })

    def test_rejects_unknown_node_type(self):
        with pytest.raises(AuthoringError, match="unknown node type"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"}, {"id": "n1", "type": "action:launch_missiles"}],
                "edges": [{"from": "t1", "to": "n1"}],
            })

    def test_rejects_duplicate_ids(self):
        with pytest.raises(AuthoringError, match="unique"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"}, {"id": "t1", "type": "action:add_note"}],
                "edges": [],
            })

    def test_rejects_edge_to_missing_node(self):
        with pytest.raises(AuthoringError, match="doesn't exist"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"}],
                "edges": [{"from": "t1", "to": "ghost"}],
            })

    def test_rejects_unreachable_node(self):
        with pytest.raises(AuthoringError, match="not reachable"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"},
                          {"id": "n1", "type": "action:add_note"},
                          {"id": "orphan", "type": "action:add_note"}],
                "edges": [{"from": "t1", "to": "n1"}],
            })

    def test_wait_needs_positive_hours(self):
        with pytest.raises(AuthoringError, match="positive 'hours'"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"}, {"id": "w", "type": "wait", "hours": 0}],
                "edges": [{"from": "t1", "to": "w"}],
            })

    def test_condition_predicate_is_validated(self):
        with pytest.raises(AuthoringError, match="condition node"):
            authoring.validate_graph({
                "nodes": [{"id": "t1", "type": "trigger"},
                          {"id": "c", "type": "condition", "predicate": {"field": "bogus", "op": "eq", "value": 1}}],
                "edges": [{"from": "t1", "to": "c"}],
            })


class TestValidateTrigger:
    def test_event_needs_kind(self):
        with pytest.raises(AuthoringError, match="needs a 'kind'"):
            authoring.validate_trigger({"type": "event"})

    def test_state_validates_predicate(self):
        with pytest.raises(AuthoringError, match="predicate"):
            authoring.validate_trigger({"type": "state", "predicate": {"field": "bogus", "op": "eq", "value": 1}})

    def test_unknown_type_rejected(self):
        with pytest.raises(AuthoringError, match="must be 'event' or 'state'"):
            authoring.validate_trigger({"type": "manual"})


class TestSlugify:
    def test_basic(self):
        assert authoring.slugify("Cooling Lead → Notify!") == "cooling-lead-notify"

    def test_empty_falls_back(self):
        assert authoring.slugify("  ") == "flow"


class TestCreateDraft:
    def test_creates_with_unique_slug(self):
        conn = FakeConn(
            fetchall_queue=[[]],           # _unique_slug: none taken
            fetchone_queue=[("new-id",)],  # RETURNING id
        )
        fid = authoring.create_draft(conn, name="My Flow", description="d",
                                     trigger=EVENT_TRIGGER, graph=GOOD_GRAPH, created_by="erez")
        assert fid == "new-id"
        insert = [s for s, _ in conn.executed if s.startswith("INSERT INTO flow_definitions")]
        assert len(insert) == 1

    def test_rejects_invalid_graph_before_insert(self):
        conn = FakeConn()
        with pytest.raises(AuthoringError):
            authoring.create_draft(conn, name="x", description=None,
                                   trigger=EVENT_TRIGGER, graph={"nodes": [], "edges": []}, created_by="e")
        assert not any(s.startswith("INSERT") for s, _ in conn.executed)

    def test_slug_collision_appends_suffix(self):
        conn = FakeConn(
            fetchall_queue=[[("my-flow",)]],   # base taken
            fetchone_queue=[("id2",)],
        )
        authoring.create_draft(conn, name="My Flow", description=None,
                               trigger=EVENT_TRIGGER, graph=GOOD_GRAPH, created_by="e")
        insert = [(s, p) for s, p in conn.executed if s.startswith("INSERT INTO flow_definitions")]
        assert insert[0][1][0] == "my-flow-2"


class TestUpdateDraft:
    def _load_row(self, status="draft"):
        # load_flow SELECT → (id, slug, version, status, live, name, desc, graph, trigger)
        return ("f1", "my-flow", 1, status, False, "My Flow", "d", GOOD_GRAPH, EVENT_TRIGGER)

    def test_updates_a_draft(self):
        conn = FakeConn(fetchone_queue=[self._load_row("draft")])
        authoring.update_draft(conn, "f1", name="Renamed")
        upd = [(s, p) for s, p in conn.executed if s.startswith("UPDATE flow_definitions SET")]
        assert len(upd) == 1
        assert "Renamed" in upd[0][1]

    def test_refuses_to_edit_a_published_flow(self):
        conn = FakeConn(fetchone_queue=[self._load_row("published")])
        with pytest.raises(AuthoringError, match="immutable"):
            authoring.update_draft(conn, "f1", name="x")

    def test_missing_flow_raises(self):
        conn = FakeConn(fetchone_queue=[None])
        with pytest.raises(AuthoringError, match="not found"):
            authoring.update_draft(conn, "f1", name="x")


class TestPublish:
    def _load_row(self, status="draft"):
        return ("f1", "my-flow", 1, status, False, "My Flow", "d", GOOD_GRAPH, EVENT_TRIGGER)

    def test_publishes_and_archives_prior(self):
        conn = FakeConn(fetchone_queue=[self._load_row("draft")])
        authoring.publish(conn, "f1", simulation={"fires": 34, "blocked": 6})
        archive = [s for s, _ in conn.executed if s.startswith("UPDATE flow_definitions SET status = 'archived'")]
        publish = [s for s, _ in conn.executed if s.startswith("UPDATE flow_definitions SET status = 'published'")]
        assert len(archive) == 1 and len(publish) == 1

    def test_refuses_without_a_simulation(self):
        conn = FakeConn(fetchone_queue=[self._load_row("draft")])
        with pytest.raises(AuthoringError, match="requires a completed simulation"):
            authoring.publish(conn, "f1", simulation={})

    def test_only_a_draft_can_publish(self):
        conn = FakeConn(fetchone_queue=[self._load_row("published")])
        with pytest.raises(AuthoringError, match="only a draft"):
            authoring.publish(conn, "f1", simulation={"fires": 1})


class TestSetStatus:
    def _row(self, status):
        return ("f1", "my-flow", 1, status, False, "n", "d", GOOD_GRAPH, EVENT_TRIGGER)

    def test_pause_published(self):
        conn = FakeConn(fetchone_queue=[self._row("published")])
        assert authoring.set_status(conn, "f1", action="pause") == "paused"

    def test_resume_checks_no_other_published(self):
        conn = FakeConn(fetchone_queue=[self._row("paused"), None])  # load, then the "other published?" check
        assert authoring.set_status(conn, "f1", action="resume") == "published"

    def test_resume_blocked_when_another_is_published(self):
        conn = FakeConn(fetchone_queue=[self._row("paused"), (1,)])
        with pytest.raises(AuthoringError, match="already published"):
            authoring.set_status(conn, "f1", action="resume")

    def test_illegal_transition_rejected(self):
        conn = FakeConn(fetchone_queue=[self._row("draft")])
        with pytest.raises(AuthoringError, match="cannot pause a draft"):
            authoring.set_status(conn, "f1", action="pause")


class TestSetLive:
    def _row(self, status):
        return ("f1", "my-flow", 1, status, False, "n", "d", GOOD_GRAPH, EVENT_TRIGGER)

    def test_only_published_can_go_live(self):
        conn = FakeConn(fetchone_queue=[self._row("draft")])
        with pytest.raises(AuthoringError, match="only a published flow"):
            authoring.set_live(conn, "f1", live=True)

    def test_published_can_go_live(self):
        conn = FakeConn(fetchone_queue=[self._row("published")])
        authoring.set_live(conn, "f1", live=True)
        assert any("live = %s" in s or "SET live" in s for s, _ in conn.executed)
