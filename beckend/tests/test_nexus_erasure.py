"""
Tests for nexus.erasure — right-to-be-forgotten. The cascade ORDER is the whole
point (leads + sessions are SET NULL on person delete, so they must go first,
and sessions must precede person so messages cascade), so the tests assert the
exact delete order, the counts, the erasure_log write, and the not-found no-op.
"""

from nexus import erasure


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append(" ".join(sql.split()))

    def fetchone(self):
        return self._conn.fetchone_queue.pop(0) if self._conn.fetchone_queue else None

    def fetchall(self):
        return self._conn.fetchall_queue.pop(0) if self._conn.fetchall_queue else []


class FakeConn:
    def __init__(self, *, fetchone=None, fetchall=None):
        self.executed = []
        self.fetchone_queue = list(fetchone or [])
        self.fetchall_queue = list(fetchall or [])

    def cursor(self):
        return FakeCursor(self)


def _delete_order(conn):
    """Indices of each DELETE / INSERT in execution order."""
    order = {}
    for i, stmt in enumerate(conn.executed):
        for tag in ("DELETE FROM bot_events", "DELETE FROM leads",
                    "DELETE FROM sessions", "DELETE FROM person ",
                    "INSERT INTO erasure_log"):
            if stmt.startswith(tag):
                order[tag.strip()] = i
    return order


_COUNTS = (5, 2, 1, 3, 0, 2, 1, 9, 0)   # messages, identity, profile, summaries,
#                                          notes, opps, bookings, interactions, merges


class TestErasePerson:
    def test_not_found_returns_none_and_deletes_nothing(self):
        conn = FakeConn(fetchone=[None])
        assert erasure.erase_person(conn, "11111111-1111-1111-1111-111111111111") is None
        assert not any(s.startswith("DELETE") for s in conn.executed)

    def test_full_erasure_order_counts_and_log(self):
        conn = FakeConn(
            fetchone=[(1,), _COUNTS],            # existence, then the count tuple
            fetchall=[[("sess-1",), ("sess-2",)]])  # session ids
        counts = erasure.erase_person(conn, "p-1", requested_by="operator")

        # counts surface both the cascade-table counts and the direct rowcounts
        assert counts["messages"] == 5
        assert counts["interactions"] == 9
        assert counts["opportunities"] == 2
        assert counts["leads"] == 1 and counts["sessions"] == 1 and counts["person"] == 1

        # THE invariant: bot_events → leads → sessions → person → log, in order.
        o = _delete_order(conn)
        assert o["DELETE FROM bot_events"] < o["DELETE FROM leads"]
        assert o["DELETE FROM leads"] < o["DELETE FROM sessions"]
        assert o["DELETE FROM sessions"] < o["DELETE FROM person"]
        assert o["DELETE FROM person"] < o["INSERT INTO erasure_log"]

    def test_no_sessions_still_completes(self):
        conn = FakeConn(fetchone=[(1,), _COUNTS], fetchall=[[]])
        counts = erasure.erase_person(conn, "p-2")
        assert counts["person"] == 1
        assert any(s.startswith("INSERT INTO erasure_log") for s in conn.executed)
