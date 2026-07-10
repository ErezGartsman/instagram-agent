"""
tests.test_nexus_flows_verifier — the Verifier Loop panel. Pattern B
(FakeConn) for the SQL verifiers; real tmp files (via FLOWS_MEMORY_DIR) for
the circuit breaker, since its whole mandate is reading the failure ledger.
"""
import datetime

import pytest

from nexus.flows import memory as flow_memory
from nexus.flows import verifier
from tests._flows_fakes import FakeConn


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWS_MEMORY_DIR", str(tmp_path / "flows_memory"))
    return tmp_path / "flows_memory"


STATE_TRIGGER = {
    "type": "state",
    "predicate": {"all": [
        {"field": "stage", "op": "in", "value": ["qualified", "captured", "briefed"]},
        {"field": "hours_since_last", "op": "gte", "value": 36},
    ]},
}


def _signals_row(person_id="p1", stage="qualified", hours_since_last=40.0):
    entered = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc)
    return (person_id, "o1", stage, entered, "whatsapp", hours_since_last, 12.0)


def _verify(conn, **kw):
    defaults = {"person_id": "p1", "text": "hi there", "source": "flow:test-flow",
                "flow_slug": "test-flow"}
    defaults.update(kw)
    return verifier.verify_send(conn, **defaults)


class TestStaleness:
    def test_abstains_for_event_triggers(self):
        # Event trigger: no live-signals lookup should even happen for staleness.
        conn = FakeConn(fetchall_queue=[[]], fetchone_queue=[None, None])
        result = _verify(conn, trigger={"type": "event", "kind": "booking_canceled"})
        staleness = next(v for v in result.verdicts if v.verifier == "staleness")
        assert staleness.decision == "approve"

    def test_rejects_when_predicate_no_longer_holds(self):
        # The lead replied between dispatch and execution: hours_since_last is
        # now 0.1 — the cooling-lead condition evaporated.
        conn = FakeConn(
            fetchall_queue=[
                [_signals_row(hours_since_last=0.1)],   # staleness: live signals
                [],                                      # duplicate_content: outbound bodies
            ],
            fetchone_queue=[None, None],                 # booking, recent_inbound
        )
        result = _verify(conn, trigger=STATE_TRIGGER)
        assert result.decision == "reject"
        assert result.blocking.verifier == "staleness"
        assert result.blocking.reason == "stale_trigger"

    def test_rejects_when_opportunity_closed_since_dispatch(self):
        conn = FakeConn(
            fetchall_queue=[[], []],       # signals: no open opp; duplicates: none
            fetchone_queue=[None, None],
        )
        result = _verify(conn, trigger=STATE_TRIGGER)
        assert result.decision == "reject"
        assert result.blocking.reason == "stale_trigger"
        assert "closed" in result.blocking.detail

    def test_approves_when_condition_still_holds(self):
        conn = FakeConn(
            fetchall_queue=[[_signals_row(hours_since_last=40.0)], []],
            fetchone_queue=[None, None],
        )
        result = _verify(conn, trigger=STATE_TRIGGER)
        assert result.decision == "approve"


class TestDuplicateContent:
    def test_rejects_normalized_match(self):
        conn = FakeConn(
            fetchall_queue=[[("  HI   there \n",)]],   # duplicate query (no trigger -> staleness abstains)
            fetchone_queue=[None, None],
        )
        result = _verify(conn, text="hi there")
        assert result.decision == "reject"
        assert result.blocking.verifier == "duplicate_content"

    def test_approves_different_content(self):
        conn = FakeConn(
            fetchall_queue=[[("a completely different message",)]],
            fetchone_queue=[None, None],
        )
        result = _verify(conn, text="hi there")
        assert result.decision == "approve"


class TestUpcomingBooking:
    def test_rejects_when_scheduled_booking_exists(self):
        conn = FakeConn(
            fetchall_queue=[[]],           # duplicates: none
            fetchone_queue=[(1,), None],   # booking: exists; recent_inbound: none
        )
        result = _verify(conn)
        assert result.decision == "reject"
        assert result.blocking.verifier == "upcoming_booking"


class TestRecentInbound:
    def test_defers_when_person_wrote_recently(self):
        conn = FakeConn(
            fetchall_queue=[[]],
            fetchone_queue=[None, (1,)],   # booking: none; recent inbound: yes
        )
        result = _verify(conn)
        assert result.decision == "defer"
        assert result.blocking.verifier == "recent_inbound"
        assert result.blocking.defer_hours == 2.0


class TestCircuitBreaker:
    def _seed_failures(self, n, reason="stale_trigger"):
        for _ in range(n):
            flow_memory.record_failure("send_rejected", flow_slug="test-flow",
                                       person_id="p1", reason=reason)

    def test_opens_at_threshold_and_records_a_lesson(self, _memory_dir):
        self._seed_failures(3)
        conn = FakeConn(fetchall_queue=[[]], fetchone_queue=[None, None])
        result = _verify(conn)
        assert result.decision == "reject"
        assert result.blocking.verifier == "circuit_breaker"
        lessons = (_memory_dir / "lessons.jsonl").read_text(encoding="utf-8")
        assert "circuit opened" in lessons

    def test_closed_below_threshold(self):
        self._seed_failures(2)
        conn = FakeConn(fetchall_queue=[[]], fetchone_queue=[None, None])
        assert _verify(conn).decision == "approve"

    def test_breaker_rejections_do_not_feed_the_breaker(self):
        """The self-perpetuation guard: circuit_breaker-caused rejections are
        excluded from the count, so the circuit can close again once the
        UNDERLYING failures age out of the window."""
        self._seed_failures(5, reason="circuit_breaker")
        conn = FakeConn(fetchall_queue=[[]], fetchone_queue=[None, None])
        assert _verify(conn).decision == "approve"

    def test_empty_memory_fails_open(self):
        conn = FakeConn(fetchall_queue=[[]], fetchone_queue=[None, None])
        assert _verify(conn).decision == "approve"


class TestAggregation:
    def test_full_panel_reports_even_after_a_reject(self):
        """A true panel: every verifier's verdict is recorded, not just the
        first reject — this is the shadow-review data."""
        conn = FakeConn(
            fetchall_queue=[[], []],       # staleness (closed opp -> reject), duplicates
            fetchone_queue=[None, None],
        )
        result = _verify(conn, trigger=STATE_TRIGGER)
        assert result.decision == "reject"
        assert len(result.verdicts) == 5   # all five verifiers reported
        assert {v.verifier for v in result.verdicts} == {
            "staleness", "duplicate_content", "upcoming_booking",
            "recent_inbound", "circuit_breaker",
        }

    def test_reject_outranks_defer(self):
        conn = FakeConn(
            fetchall_queue=[[("hi there",)]],   # duplicate -> reject
            fetchone_queue=[None, (1,)],        # recent inbound -> defer
        )
        result = _verify(conn, text="hi there")
        assert result.decision == "reject"
        assert result.blocking.verifier == "duplicate_content"

    def test_rejection_recorded_to_failure_memory_when_record_true(self, _memory_dir):
        conn = FakeConn(fetchall_queue=[[("hi there",)]], fetchone_queue=[None, None])
        _verify(conn, text="hi there", record=True)
        failures = (_memory_dir / "failures.jsonl").read_text(encoding="utf-8")
        assert "duplicate_content" in failures

    def test_shadow_record_false_writes_nothing(self, _memory_dir):
        conn = FakeConn(fetchall_queue=[[("hi there",)]], fetchone_queue=[None, None])
        _verify(conn, text="hi there", record=False)
        assert not (_memory_dir / "failures.jsonl").exists()

    def test_crashed_verifier_abstains_and_is_logged(self, _memory_dir, monkeypatch):
        def boom(conn, ctx):
            raise RuntimeError("verifier exploded")
        monkeypatch.setattr(verifier, "_REGISTRY", (boom, verifier._verify_recent_inbound))
        conn = FakeConn(fetchone_queue=[None])
        result = _verify(conn)
        assert result.decision == "approve"   # fail-open: advisory layer only
        assert any(v.decision == "error" for v in result.verdicts)
        failures = (_memory_dir / "failures.jsonl").read_text(encoding="utf-8")
        assert "verifier_crashed" in failures
