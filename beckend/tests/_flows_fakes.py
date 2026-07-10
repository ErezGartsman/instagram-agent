"""
tests._flows_fakes — a shared fake psycopg2 harness for the Flows engine
suite (test_nexus_flows_*.py, test_nexus_qualification.py).

Extends the FakeConn/FakeCursor pattern already established in
test_nexus_hooks.py with fetchall() and a per-execute rowcount queue, both
needed by nexus/flows/*'s heavier queries. This is a plain, explicitly
imported helper module (not a conftest.py — no autouse/hidden magic); the
repo's "every test file is self-contained" convention is about avoiding
implicit pytest fixture wiring, not about hand-duplicating an identical
~40-line harness across four sibling files where it would only drift.

fetchone_queue / fetchall_queue / rowcount_queue are FIFO lists popped in the
EXACT order the code under test issues its execute/fetchone/fetchall calls —
callers must pre-load them in that order (same discipline as
test_nexus_hooks.FakeConn.fetch_queue).
"""
from __future__ import annotations


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        stmt = " ".join(sql.split())
        self._conn.executed.append((stmt, params))
        if self._conn.fail_prefix and stmt.startswith(self._conn.fail_prefix):
            raise RuntimeError(f"injected failure at: {self._conn.fail_prefix!r}")
        self.rowcount = self._conn.rowcount_queue.pop(0) if self._conn.rowcount_queue else 1

    def fetchone(self):
        return self._conn.fetchone_queue.pop(0) if self._conn.fetchone_queue else None

    def fetchall(self):
        return self._conn.fetchall_queue.pop(0) if self._conn.fetchall_queue else []


class FakeConn:
    def __init__(self, *, fetchone_queue=None, fetchall_queue=None,
                rowcount_queue=None, fail_prefix=None):
        self.executed = []
        self.fetchone_queue = list(fetchone_queue or [])
        self.fetchall_queue = list(fetchall_queue or [])
        self.rowcount_queue = list(rowcount_queue or [])
        self.fail_prefix = fail_prefix
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def stmts(conn: FakeConn, prefix: str) -> list[str]:
    return [s for s, _ in conn.executed if s.startswith(prefix)]
