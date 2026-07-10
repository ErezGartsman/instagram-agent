"""
tests.test_nexus_flows_memory — the file-based runtime memory. Real files in
pytest's tmp_path (this module's whole point is file behavior — mocking the
filesystem would test nothing), pointed at via the FLOWS_MEMORY_DIR env var.
"""
import datetime
import json
import threading

import pytest

from nexus.flows import memory


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWS_MEMORY_DIR", str(tmp_path / "flows_memory"))
    return tmp_path / "flows_memory"


class TestRecordAndRecall:
    def test_failure_roundtrip(self, _memory_dir):
        memory.record_failure("send_rejected", flow_slug="cooling-lead-nudge",
                              person_id="p1", verifier="staleness",
                              reason="stale_trigger", detail="lead replied")
        found = memory.recent_failures(flow_slug="cooling-lead-nudge", person_id="p1")
        assert len(found) == 1
        assert found[0]["verifier"] == "staleness"
        assert found[0]["reason"] == "stale_trigger"
        assert "at" in found[0] and "pid" in found[0]

    def test_filters_by_person_and_flow(self):
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1", reason="x")
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p2", reason="x")
        memory.record_failure("send_rejected", flow_slug="f2", person_id="p1", reason="x")
        assert memory.failure_count(flow_slug="f1", person_id="p1") == 1
        assert memory.failure_count(flow_slug="f1") == 2
        assert memory.failure_count(person_id="p1") == 2

    def test_exclude_reasons(self):
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1",
                              reason="circuit_breaker")
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1",
                              reason="stale_trigger")
        assert memory.failure_count(flow_slug="f1", person_id="p1",
                                    exclude_reasons=("circuit_breaker",)) == 1

    def test_window_filter_drops_old_entries(self, _memory_dir):
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1", reason="x")
        # Manually append an entry timestamped outside the window.
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
        with open(_memory_dir / "failures.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": old.isoformat(), "kind": "send_rejected",
                                "flow_slug": "f1", "person_id": "p1", "reason": "x"}) + "\n")
        assert memory.failure_count(flow_slug="f1", person_id="p1", within_days=7) == 1

    def test_corrupt_line_is_skipped_not_fatal(self, _memory_dir):
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1", reason="x")
        with open(_memory_dir / "failures.jsonl", "a", encoding="utf-8") as f:
            f.write("{this is not json\n")
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1", reason="y")
        assert memory.failure_count(flow_slug="f1", person_id="p1") == 2

    def test_missing_dir_reads_empty_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLOWS_MEMORY_DIR", str(tmp_path / "never-created"))
        assert memory.recent_failures() == []
        assert memory.failure_count() == 0

    def test_unwritable_dir_swallows_never_raises(self, tmp_path, monkeypatch):
        # Point the "directory" at an existing FILE — mkdir/open must fail,
        # and record_* must swallow it (a memory failure never breaks a send).
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file, not a directory")
        monkeypatch.setenv("FLOWS_MEMORY_DIR", str(blocker))
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1", reason="x")
        memory.record_lesson("this write goes nowhere, quietly")
        memory.record_efficiency("sweep_cycle", duration_ms=1.0)


class TestParallelWriters:
    def test_concurrent_appends_produce_only_whole_lines(self, _memory_dir):
        """The 'parallel subagents' contract: N threads appending
        concurrently must yield exactly N*M parseable records — no torn or
        interleaved lines."""
        threads_n, per_thread = 8, 25

        def writer(tid: int):
            for i in range(per_thread):
                memory.record_failure("send_rejected", flow_slug=f"flow-{tid}",
                                      person_id=f"p-{i}", reason="parallel-test")

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(threads_n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = (_memory_dir / "failures.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == threads_n * per_thread
        parsed = [json.loads(line) for line in lines]   # raises on any torn line
        assert all(p["reason"] == "parallel-test" for p in parsed)


class TestIndex:
    def test_index_regenerates_with_patterns_and_lessons(self, _memory_dir):
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p1",
                              verifier="duplicate_content", reason="duplicate_content")
        memory.record_failure("send_rejected", flow_slug="f1", person_id="p2",
                              verifier="duplicate_content", reason="duplicate_content")
        memory.record_lesson("circuit opened: flow=f1 person=p9 — 3 failed attempts")
        index = (_memory_dir / "MEMORY_INDEX.md").read_text(encoding="utf-8")
        assert "send_rejected · duplicate_content` × 2" in index
        assert "circuit opened: flow=f1 person=p9" in index
