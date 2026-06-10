"""
Failure-injection tests for nexus.hooks — these mechanically prove the hook
contract the live bot depends on:

  1. A hook NEVER raises, no matter where its SQL fails.
  2. Hook A (shared connection) preserves SAVEPOINT discipline: on failure it
     issues ROLLBACK TO SAVEPOINT so the caller's transaction is never left
     aborted — the silent-failure mode that would break every later legacy
     statement in the webhook turn.
  3. Hook B (own connection) commits on success and swallows on failure.

The FakeConn harness records every SQL statement and can be told to raise on
the first statement matching a prefix — letting us inject a failure at any
exact point in the hook's sequence.
"""

import contextlib
import urllib.parse

import pytest

from nexus import db as nexus_db
from nexus import hooks


# ─── Fake psycopg2 harness ────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        stmt = " ".join(sql.split())   # normalize whitespace for matching
        self._conn.executed.append(stmt)
        fail_prefix = self._conn.fail_prefix
        if fail_prefix and stmt.startswith(fail_prefix):
            raise RuntimeError(f"injected failure at: {fail_prefix!r}")

    def fetchone(self):
        if self._conn.fetch_queue:
            return self._conn.fetch_queue.pop(0)
        return None


class FakeConn:
    """Records statements; optional fail_prefix raises on a matching execute."""

    def __init__(self, fetch_queue=None, fail_prefix=None):
        self.executed = []
        self.fetch_queue = list(fetch_queue or [])
        self.fail_prefix = fail_prefix
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _stmts(conn, prefix):
    return [s for s in conn.executed if s.startswith(prefix)]


# ─── Hook A — on_channel_session ─────────────────────────────────────────────

class TestHookASessionSpine:
    def test_happy_path_existing_identity(self):
        conn = FakeConn(fetch_queue=[("person-uuid-1",)])  # identity lookup hit
        result = hooks.on_channel_session(conn, "sess-1", "telegram", "12345")

        assert result == "person-uuid-1"
        assert _stmts(conn, "SAVEPOINT nexus_hook")
        assert _stmts(conn, "RELEASE SAVEPOINT nexus_hook")
        assert not _stmts(conn, "ROLLBACK TO SAVEPOINT")
        # the session got stamped
        assert _stmts(conn, "UPDATE sessions SET person_id")

    def test_failure_mid_hook_rolls_back_to_savepoint(self):
        # Identity lookup misses → create path → INSERT INTO person explodes.
        conn = FakeConn(fetch_queue=[None], fail_prefix="INSERT INTO person")
        result = hooks.on_channel_session(conn, "sess-1", "telegram", "12345")

        assert result is None                          # contract: swallow
        assert _stmts(conn, "ROLLBACK TO SAVEPOINT nexus_hook")  # tx rescued
        assert _stmts(conn, "RELEASE SAVEPOINT nexus_hook")
        assert not _stmts(conn, "UPDATE sessions SET person_id")

    def test_failure_on_session_stamp_rolls_back(self):
        conn = FakeConn(fetch_queue=[("person-uuid-1",)],
                        fail_prefix="UPDATE sessions SET person_id")
        result = hooks.on_channel_session(conn, "sess-1", "instagram", "ig-9")

        assert result is None
        assert _stmts(conn, "ROLLBACK TO SAVEPOINT nexus_hook")

    def test_dead_connection_at_savepoint_open(self):
        # Even the SAVEPOINT itself failing must not raise.
        conn = FakeConn(fail_prefix="SAVEPOINT nexus_hook")
        result = hooks.on_channel_session(conn, "sess-1", "telegram", "12345")

        assert result is None
        # nothing else was attempted on the broken connection
        assert conn.executed == ["SAVEPOINT nexus_hook"]

    def test_invalid_channel_swallowed(self):
        # resolve_or_create_person raises ValueError for junk channels —
        # the hook must swallow that too and rescue the savepoint.
        conn = FakeConn()
        result = hooks.on_channel_session(conn, "sess-1", "carrier-pigeon", "x")

        assert result is None
        assert _stmts(conn, "ROLLBACK TO SAVEPOINT nexus_hook")


# ─── Hook B — on_lead_captured ───────────────────────────────────────────────

@contextlib.contextmanager
def _fake_provider(conn):
    yield conn


class TestHookBCaptureSpine:
    def _wire(self, monkeypatch, conn):
        monkeypatch.setattr(nexus_db, "_conn_provider",
                            lambda: _fake_provider(conn))

    def test_happy_path_commits_full_spine(self, monkeypatch):
        conn = FakeConn(fetch_queue=[
            None,                       # identity lookup miss → create person
            ("person-uuid-9",),         # INSERT person RETURNING id
            ("identity-uuid-1",),       # INSERT person_identity RETURNING id
            None,                       # phone identity lookup miss → link
            ("sess-uuid-7",),           # SELECT session_id FROM leads
            None,                       # open-opportunity lookup miss → create
            ("opp-uuid-3",),            # INSERT opportunities RETURNING id
            ("person-uuid-9", "engaged", "instagram", None),  # advance_stage read
        ])
        self._wire(monkeypatch, conn)

        hooks.on_lead_captured("lead-1", channel="instagram",
                               chat_id="ig-77", phone="0501234567")

        assert conn.commits == 1
        assert _stmts(conn, "UPDATE leads SET person_id")
        assert _stmts(conn, "INSERT INTO person_identity (person_id, channel, external_id) VALUES (%s, 'phone'")
        assert _stmts(conn, "INSERT INTO opportunities")
        assert _stmts(conn, "UPDATE opportunities SET stage")
        assert _stmts(conn, "INSERT INTO interactions")

    def test_failure_anywhere_is_swallowed_and_not_committed(self, monkeypatch):
        conn = FakeConn(fetch_queue=[None],
                        fail_prefix="INSERT INTO person ")
        self._wire(monkeypatch, conn)

        # Must not raise — the webhook turn is already past the user ack.
        hooks.on_lead_captured("lead-1", channel="telegram",
                               chat_id="12345", phone="0501234567")
        assert conn.commits == 0

    def test_unconfigured_bridge_is_swallowed(self, monkeypatch):
        # If main.py's configure() never ran (misdeploy), the hook must still
        # not raise into the webhook turn.
        monkeypatch.setattr(nexus_db, "_conn_provider", None)
        hooks.on_lead_captured("lead-1", channel="telegram",
                               chat_id="12345", phone="0501234567")

    def test_invalid_phone_still_builds_spine(self, monkeypatch):
        # A non-normalizable phone links no identity but the opportunity and
        # interaction must still be written (capture is the business event).
        conn = FakeConn(fetch_queue=[
            ("person-uuid-9",),         # identity lookup hit
            ("sess-uuid-7",),           # SELECT session_id FROM leads
            None,                       # open-opportunity miss → create
            ("opp-uuid-3",),            # INSERT opportunities RETURNING id
            ("person-uuid-9", "engaged", "telegram", None),
        ])
        self._wire(monkeypatch, conn)

        hooks.on_lead_captured("lead-2", channel="telegram",
                               chat_id="12345", phone="not-a-phone")

        assert conn.commits == 1
        assert not _stmts(conn, "INSERT INTO person_identity (person_id, channel, external_id) VALUES (%s, 'phone'")
        assert _stmts(conn, "INSERT INTO interactions")


# ─── Hooks C1–C5 — on_funnel_event ───────────────────────────────────────────

class TestHookCFunnelEvent:
    def _wire(self, monkeypatch, conn):
        monkeypatch.setattr(nexus_db, "_conn_provider",
                            lambda: _fake_provider(conn))

    def test_stage_advance_commits_interaction_and_stage(self, monkeypatch):
        conn = FakeConn(fetch_queue=[
            ("person-uuid-1",),                               # session stamp
            ("opp-uuid-1",),                                  # open opp found
            ("person-uuid-1", "engaged", "telegram", None),   # advance read
        ])
        self._wire(monkeypatch, conn)

        hooks.on_funnel_event("qualified", "telegram",
                              session_id="sess-1", stage="qualified",
                              dedup_key="qualified:sess-1")

        assert conn.commits == 1
        assert _stmts(conn, "UPDATE opportunities SET stage")
        assert _stmts(conn, "INSERT INTO interactions")

    def test_engaged_opens_opportunity_without_advance(self, monkeypatch):
        # stage='engaged' must ensure an open opportunity but never attempt a
        # forward move (engaged→engaged is not forward; skip it entirely).
        conn = FakeConn(fetch_queue=[
            ("person-uuid-1",),     # session stamp
            None,                   # open-opp lookup miss → create
            ("opp-uuid-2",),        # INSERT opportunities RETURNING id
        ])
        self._wire(monkeypatch, conn)

        hooks.on_funnel_event("icebreaker_hit", "instagram",
                              session_id="sess-2", stage="engaged")

        assert conn.commits == 1
        assert _stmts(conn, "INSERT INTO opportunities")
        assert not _stmts(conn, "UPDATE opportunities SET stage")
        assert _stmts(conn, "INSERT INTO interactions")

    def test_unstamped_session_logs_interaction_only(self, monkeypatch):
        # Hook A failed earlier → person NULL: count the signal (bot_events
        # parity) but never touch opportunities.
        conn = FakeConn(fetch_queue=[(None,)])
        self._wire(monkeypatch, conn)

        hooks.on_funnel_event("context_provided", "instagram",
                              session_id="sess-3", stage="briefed")

        assert conn.commits == 1
        assert not _stmts(conn, "INSERT INTO opportunities")
        assert not _stmts(conn, "UPDATE opportunities")
        assert _stmts(conn, "INSERT INTO interactions")

    def test_failure_is_swallowed(self, monkeypatch):
        conn = FakeConn(fail_prefix="SELECT person_id FROM sessions")
        self._wire(monkeypatch, conn)

        hooks.on_funnel_event("qualified", "telegram",
                              session_id="sess-4", stage="qualified")
        assert conn.commits == 0

    def test_unconfigured_bridge_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(nexus_db, "_conn_provider", None)
        hooks.on_funnel_event("qualified", "telegram",
                              session_id="sess-5", stage="qualified")


# ─── Hook D — whatsapp_cta_url ───────────────────────────────────────────────

_PLAIN = "https://wa.me/972501234567"


class TestHookDWhatsAppCta:
    """The conversion CTA: the user must NEVER receive a broken link.
    Every failure mode demanded by the review is injected here."""

    def _wire(self, monkeypatch, conn):
        monkeypatch.setattr(nexus_db, "_conn_provider",
                            lambda: _fake_provider(conn))

    def test_happy_path_prefill_is_well_formed(self, monkeypatch):
        conn = FakeConn(fetch_queue=[("AB2C3D",)])
        self._wire(monkeypatch, conn)

        url = hooks.whatsapp_cta_url("972501234567", "instagram", "ig-77")

        assert url.startswith(_PLAIN + "?text=")
        assert url.isascii()
        assert len(url) <= hooks._WA_URL_MAX
        # no raw spaces/quotes — everything percent-encoded (safe="")
        assert " " not in url and '"' not in url and "'" not in url
        # the ref survives a round-trip decode exactly
        decoded = urllib.parse.unquote(url.split("?text=", 1)[1])
        assert "AB2C3D" in decoded
        assert decoded == hooks._WA_PREFILL_TEMPLATE.format(ref="AB2C3D")

    def test_no_person_falls_back_to_plain(self, monkeypatch):
        conn = FakeConn(fetch_queue=[None])
        self._wire(monkeypatch, conn)
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-0") == _PLAIN

    def test_null_ref_falls_back_to_plain(self, monkeypatch):
        conn = FakeConn(fetch_queue=[(None,)])
        self._wire(monkeypatch, conn)
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-1") == _PLAIN

    def test_db_failure_falls_back_to_plain(self, monkeypatch):
        conn = FakeConn(fail_prefix="SELECT p.wa_ref_code")
        self._wire(monkeypatch, conn)
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-2") == _PLAIN

    def test_unconfigured_bridge_falls_back_to_plain(self, monkeypatch):
        monkeypatch.setattr(nexus_db, "_conn_provider", None)
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-3") == _PLAIN

    def test_encoding_explosion_falls_back_to_plain(self, monkeypatch):
        conn = FakeConn(fetch_queue=[("AB2C3D",)])
        self._wire(monkeypatch, conn)

        def boom(*a, **kw):
            raise UnicodeError("injected encoder failure")

        monkeypatch.setattr(hooks.urllib.parse, "quote", boom)
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-4") == _PLAIN

    def test_oversized_result_falls_back_to_plain(self, monkeypatch):
        # A pathological template (or ref) producing a huge URL must trip the
        # length guard, not ship a possibly-truncated link.
        conn = FakeConn(fetch_queue=[("AB2C3D",)])
        self._wire(monkeypatch, conn)
        monkeypatch.setattr(hooks, "_WA_PREFILL_TEMPLATE", ("x" * 2000) + "{ref}")
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-5") == _PLAIN

    def test_non_ascii_leak_falls_back_to_plain(self, monkeypatch):
        # If encoding ever silently passes raw unicode through, the ascii
        # guard must catch it.
        conn = FakeConn(fetch_queue=[("AB2C3D",)])
        self._wire(monkeypatch, conn)
        monkeypatch.setattr(hooks.urllib.parse, "quote", lambda s, safe="": s)
        assert hooks.whatsapp_cta_url("972501234567", "instagram", "ig-6") == _PLAIN

    def test_hostile_ref_content_stays_encoded(self, monkeypatch):
        # Defense-in-depth: even a corrupted ref value cannot break the URL —
        # quote(safe="") encodes everything; validation guarantees shape.
        conn = FakeConn(fetch_queue=[('NX"; <script>&?',)])
        self._wire(monkeypatch, conn)

        url = hooks.whatsapp_cta_url("972501234567", "instagram", "ig-7")

        assert url == _PLAIN or (
            url.startswith(_PLAIN + "?text=") and url.isascii()
            and "<" not in url and '"' not in url and "&" not in url.split("?text=", 1)[1]
        )
