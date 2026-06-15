"""
Tests for nexus.bookings — the Calendly booking webhook.

Covers the security-critical signature verification (valid / tampered / replay /
missing), defensive payload parsing (phone from each source), the deterministic
match ladder and its priority, opportunity advancement on match vs. recording-
only when unmatched, cancellation, and the never-raise contract.
"""

import contextlib
import hashlib
import hmac
import time

from nexus import bookings
from nexus import db as nexus_db


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
        stmt = " ".join(sql.split())
        self._conn.executed.append(stmt)
        # UPDATE rowcount is configurable (to exercise the cancel-before-create
        # fallback); everything else reports 1 so log_interaction sees a write.
        self.rowcount = self._conn.update_rowcount if stmt.startswith("UPDATE") else 1

    def fetchone(self):
        return self._conn.fetchone_queue.pop(0) if self._conn.fetchone_queue else None


class FakeConn:
    def __init__(self, *, fetchone=None, update_rowcount=1):
        self.executed = []
        self.fetchone_queue = list(fetchone or [])
        self.update_rowcount = update_rowcount
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def _stmts(conn, prefix):
    return [s for s in conn.executed if s.startswith(prefix)]


# ─── verify_signature (security-critical) ─────────────────────────────────────

_KEY = "whsec_test_key"
_BODY = b'{"event":"invitee.created","payload":{"uri":"abc"}}'


def _sign(body: bytes, key: str, ts: int) -> str:
    signed = str(ts).encode() + b"." + body
    v1 = hmac.new(key.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


class TestVerifySignature:
    def test_valid_signature_passes(self):
        header = _sign(_BODY, _KEY, int(time.time()))
        assert bookings.verify_signature(_BODY, header, _KEY) is True

    def test_tampered_signature_fails(self):
        header = _sign(_BODY, _KEY, int(time.time()))[:-4] + "dead"
        assert bookings.verify_signature(_BODY, header, _KEY) is False

    def test_wrong_key_fails(self):
        header = _sign(_BODY, _KEY, int(time.time()))
        assert bookings.verify_signature(_BODY, header, "other_key") is False

    def test_body_tampering_fails(self):
        header = _sign(_BODY, _KEY, int(time.time()))
        assert bookings.verify_signature(_BODY + b"x", header, _KEY) is False

    def test_stale_timestamp_fails_replay(self):
        header = _sign(_BODY, _KEY, int(time.time()) - 10_000)
        assert bookings.verify_signature(_BODY, header, _KEY) is False

    def test_missing_header_or_key_fails(self):
        header = _sign(_BODY, _KEY, int(time.time()))
        assert bookings.verify_signature(_BODY, None, _KEY) is False
        assert bookings.verify_signature(_BODY, header, "") is False

    def test_malformed_header_fails(self):
        assert bookings.verify_signature(_BODY, "garbage", _KEY) is False
        assert bookings.verify_signature(_BODY, "t=abc,v1=x", _KEY) is False


# ─── parse_invitee_payload ───────────────────────────────────────────────────

class TestParsePayload:
    def test_phone_from_text_reminder_number(self):
        body = {"payload": {"uri": "u1", "email": "A@B.COM", "name": "Dana",
                            "text_reminder_number": "+972501234567",
                            "scheduled_event": {"start_time": "2026-06-15T14:00:00Z"},
                            "tracking": {"utm_content": "AB2C3D"}}}
        p = bookings.parse_invitee_payload(body)
        assert p["uri"] == "u1"
        assert p["email"] == "a@b.com"          # lowercased
        assert p["phone"] == "+972501234567"
        assert p["token"] == "AB2C3D"
        assert p["starts_at"] == "2026-06-15T14:00:00Z"

    def test_phone_from_questions_and_answers(self):
        body = {"payload": {"uri": "u2",
                            "questions_and_answers": [
                                {"question": "What's your goal?", "answer": "זוגיות"},
                                {"question": "מספר טלפון", "answer": "050-1234567"}]}}
        p = bookings.parse_invitee_payload(body)
        assert p["phone"] == "050-1234567"

    def test_missing_fields_are_none(self):
        p = bookings.parse_invitee_payload({"payload": {"uri": "u3"}})
        assert p["phone"] is None and p["token"] is None and p["email"] is None
        assert p["join_url"] is None and p["reschedule_url"] is None

    def test_extracts_join_url_and_reschedule(self):
        body = {"payload": {
            "uri": "u4",
            "reschedule_url": "https://calendly.com/reschedule/x",
            "scheduled_event": {
                "start_time": "2026-06-17T12:00:00Z",
                "location": {"type": "google_conference",
                             "join_url": "https://meet.google.com/abc"}}}}
        p = bookings.parse_invitee_payload(body)
        assert p["join_url"] == "https://meet.google.com/abc"
        assert p["reschedule_url"] == "https://calendly.com/reschedule/x"


# ─── match_person ladder ─────────────────────────────────────────────────────

class TestMatchLadder:
    def test_token_wins_over_phone(self):
        conn = FakeConn(fetchone=[("person-token",)])   # token SELECT hits first
        pid, via = bookings.match_person(
            conn, token="AB2C3D", phone="0501234567", email="a@b.com")
        assert (pid, via) == ("person-token", "token")
        assert len(_stmts(conn, "SELECT id FROM person WHERE wa_ref_code")) == 1

    def test_phone_match_when_no_token(self):
        conn = FakeConn(fetchone=[("person-phone",)])   # phone identity SELECT hits
        pid, via = bookings.match_person(
            conn, token=None, phone="0501234567", email="a@b.com")
        assert (pid, via) == ("person-phone", "phone")

    def test_email_match_when_no_token_or_phone(self):
        # token miss is not queried (None); phone present but identity misses,
        # then email hits.
        conn = FakeConn(fetchone=[None, ("person-email",)])
        pid, via = bookings.match_person(
            conn, token=None, phone="0501234567", email="a@b.com")
        assert (pid, via) == ("person-email", "email")

    def test_no_match_returns_none(self):
        conn = FakeConn(fetchone=[None, None])
        pid, via = bookings.match_person(
            conn, token=None, phone="0501234567", email="a@b.com")
        assert (pid, via) == (None, "none")


# ─── _handle_created / _handle_canceled ──────────────────────────────────────

_CREATED = {"uri": "evt-1", "email": "a@b.com", "name": "Dana",
            "phone": "0501234567", "token": None, "starts_at": "2026-06-15T14:00:00Z"}


class TestHandleCreated:
    def test_matched_booking_advances_opportunity(self):
        conn = FakeConn(fetchone=[
            ("person-1",),                                   # phone match
            ("opp-1",),                                      # open opp exists
            ("person-1", "engaged", "calendly", None),       # advance_stage read
        ])
        via = bookings._handle_created(conn, dict(_CREATED))
        assert via == "phone"
        assert _stmts(conn, "UPDATE opportunities SET stage")     # advanced
        assert _stmts(conn, "INSERT INTO bookings")
        assert _stmts(conn, "INSERT INTO interactions")           # booking_created

    def test_unmatched_booking_is_recorded_without_advance(self):
        conn = FakeConn(fetchone=[None, None])   # phone miss, email miss
        via = bookings._handle_created(conn, dict(_CREATED))
        assert via == "none"
        assert not _stmts(conn, "INSERT INTO opportunities")
        assert not _stmts(conn, "UPDATE opportunities SET stage")
        assert _stmts(conn, "INSERT INTO bookings")              # still recorded
        assert _stmts(conn, "INSERT INTO interactions")

    def test_missing_uri_is_ignored(self):
        conn = FakeConn()
        assert bookings._handle_created(conn, {"uri": None}) == "ignored"
        assert conn.executed == []


class TestHandleCanceled:
    def test_existing_booking_marked_canceled(self):
        conn = FakeConn(fetchone=[None, None], update_rowcount=1)   # no person match
        out = bookings._handle_canceled(conn, dict(_CREATED))
        assert out == "canceled"
        assert _stmts(conn, "UPDATE bookings SET status = 'canceled'")
        assert not _stmts(conn, "INSERT INTO bookings")            # update found a row
        assert _stmts(conn, "INSERT INTO interactions")

    def test_cancel_before_create_inserts_canceled_row(self):
        conn = FakeConn(fetchone=[None, None], update_rowcount=0)   # update hits nothing
        bookings._handle_canceled(conn, dict(_CREATED))
        assert _stmts(conn, "INSERT INTO bookings")               # fallback insert


# ─── process_event (never raises) ────────────────────────────────────────────

@contextlib.contextmanager
def _provider(conn):
    yield conn


class TestProcessEvent:
    def test_unknown_event_is_ignored(self, monkeypatch):
        touched = []
        monkeypatch.setattr(nexus_db, "_conn_provider",
                            lambda: touched.append(1) or _provider(FakeConn()))
        bookings.process_event({"event": "routing_form_submission.created"})
        assert touched == []          # never even opened a connection

    def test_unconfigured_bridge_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(nexus_db, "_conn_provider", None)
        # Must not raise even though the bridge is missing.
        bookings.process_event({"event": "invitee.created",
                                "payload": {"uri": "x"}})

    def test_created_event_commits(self, monkeypatch):
        conn = FakeConn(fetchone=[None, None])   # unmatched → recorded
        monkeypatch.setattr(nexus_db, "_conn_provider", lambda: _provider(conn))
        bookings.process_event({"event": "invitee.created",
                                "payload": {"uri": "evt-9", "email": "x@y.com"}})
        assert conn.commits == 1
        assert _stmts(conn, "INSERT INTO bookings")


# ─── WhatsApp confirmation collection (Ticket 4.3) ───────────────────────────

class TestBookingConfirmation:
    def test_collected_for_matched_whatsapp_booking(self):
        conn = FakeConn(fetchone=[
            ("person-1",),                                 # phone match
            ("opp-1",),                                    # open opp exists
            ("person-1", "engaged", "calendly", None),     # advance_stage read
            ("972500000000",),                             # _whatsapp_id_for_person
        ])
        confirmations = []
        via = bookings._handle_created(conn, dict(_CREATED), confirmations)
        assert via == "phone"
        assert len(confirmations) == 1
        assert confirmations[0]["wa_id"] == "972500000000"

    def test_not_collected_when_unmatched(self):
        conn = FakeConn(fetchone=[None, None])   # phone miss, email miss
        confirmations = []
        bookings._handle_created(conn, dict(_CREATED), confirmations)
        assert confirmations == []

    def test_not_collected_without_whatsapp_identity(self):
        conn = FakeConn(fetchone=[
            ("person-1",), ("opp-1",), ("person-1", "engaged", "calendly", None),
            None,                                          # no whatsapp identity
        ])
        confirmations = []
        bookings._handle_created(conn, dict(_CREATED), confirmations)
        assert confirmations == []

    def test_callback_fires_post_commit(self, monkeypatch):
        conn = FakeConn(fetchone=[
            ("person-1",), ("opp-1",), ("person-1", "engaged", "calendly", None),
            ("972511112222",),
        ])
        monkeypatch.setattr(nexus_db, "_conn_provider", lambda: _provider(conn))
        seen = []
        bookings.process_event(
            {"event": "invitee.created",
             "payload": {"uri": "evt-x", "text_reminder_number": "+972511112222",
                         "scheduled_event": {"start_time": "2026-06-17T12:00:00Z"}}},
            on_confirmed=seen.append)
        assert len(seen) == 1
        assert seen[0]["wa_id"] == "972511112222"
