"""
One Thread Phase 2 — send-from-cockpit (WhatsApp only).

Covers three layers, no Supabase/network:
  1. _wa_send_eligibility   — the 24h WhatsApp free-form window, pure DB read.
  2. _resolve_default_channel — 'reply to last inbound', pure Python.
  3. POST /api/cockpit/thread/{person_id}/send — the composer's endpoint
     contract: always HTTP 200, {status, reason_code, detail} on any block,
     idempotent via client_token, and it must NEVER attempt a send when the
     channel isn't WhatsApp (Phase 3 territory) or eligibility says no.

Deliberately does not touch _dispatch_outreach / the Queue Action endpoint —
those are separately covered by test_cockpit_action.py and untouched here.
"""
import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

PID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def client():
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


def _cursor(fetchone_side_effect):
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchone.side_effect = fetchone_side_effect
    return cur


def _conn_returning(cur):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value = cur
    return conn


def _get_db_conn_returning(conn):
    return MagicMock(return_value=conn)


# ── _wa_send_eligibility ──────────────────────────────────────────────────────

class TestWaSendEligibility:
    def test_within_24h_is_eligible(self):
        last_inbound = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        cur = _cursor([(last_inbound,)])
        conn = _conn_returning(cur)
        result = main._wa_send_eligibility(conn, PID)
        assert result["eligible"] is True
        assert result["reason"] is None
        assert result["window_expires_at"] is not None

    def test_past_24h_is_window_expired(self):
        last_inbound = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)
        cur = _cursor([(last_inbound,)])
        conn = _conn_returning(cur)
        result = main._wa_send_eligibility(conn, PID)
        assert result["eligible"] is False
        assert result["reason"] == "window_expired"

    def test_never_messaged_is_no_inbound_yet(self):
        cur = _cursor([(None,)])
        conn = _conn_returning(cur)
        result = main._wa_send_eligibility(conn, PID)
        assert result["eligible"] is False
        assert result["reason"] == "no_inbound_yet"
        assert result["window_expires_at"] is None


# ── _resolve_default_channel ──────────────────────────────────────────────────

class TestResolveDefaultChannel:
    def test_empty_thread_defaults_whatsapp(self):
        assert main._resolve_default_channel([]) == "whatsapp"

    def test_last_lead_message_wins_even_if_operator_replied_after(self):
        messages = [
            {"role": "user", "channel": "instagram", "at": "2026-07-01T00:00:00"},
            {"role": "user", "channel": "whatsapp", "at": "2026-07-02T00:00:00"},
            {"role": "operator", "channel": "whatsapp", "at": "2026-07-03T00:00:00"},
        ]
        # Most recent LEAD-authored message is the instagram-then-whatsapp one —
        # the last 'user' row (whatsapp) should win, not the operator's reply.
        assert main._resolve_default_channel(messages) == "whatsapp"

    def test_falls_back_to_last_message_when_no_user_role_present(self):
        messages = [{"role": "assistant", "channel": "telegram", "at": "2026-07-01T00:00:00"}]
        assert main._resolve_default_channel(messages) == "telegram"


# ── POST /api/cockpit/thread/{person_id}/send ─────────────────────────────────

class TestThreadSendEndpoint:
    def _post(self, client, **body):
        body.setdefault("client_token", "tok-1")
        return client.post(f"/api/cockpit/thread/{PID}/send", json=body)

    def test_non_whatsapp_channel_is_rejected_before_touching_db(self, client):
        with patch.object(main, "get_db_conn") as gdc:
            r = self._post(client, body="hi", channel="instagram")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "channel_not_supported"
        gdc.assert_not_called()

    def test_person_not_found(self, client):
        cur = _cursor([None])   # person existence check → no row
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)):
            r = self._post(client, body="hi")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "not_found"

    def test_successful_send_is_ref_only_and_returns_message(self, client):
        # fetchone() call order: person-exists, client_token-precheck(None),
        # opportunity lookup, INSERT...RETURNING.
        sent_at = datetime.datetime(2026, 7, 9, 12, 0, tzinfo=datetime.timezone.utc)
        cur = _cursor([
            (1,),                                        # person exists
            None,                                        # no existing client_token row
            ("44444444-4444-4444-4444-444444444444",),   # open opportunity
            ("55555555-5555-5555-5555-555555555555", sent_at),  # INSERT RETURNING
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_wa_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value="972500000000"), \
             patch.object(main._KAPSO_CHANNEL, "send_text",
                          return_value='{"messages":[{"id":"wamid.ABC"}]}') as snd, \
             patch.object(main.nexus_interactions, "log_interaction") as logi:
            r = self._post(client, body="Hi Maya, here's the booking link")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["message"]["provider_message_id"] == "wamid.ABC"
        assert data["message"]["role"] == "operator"
        assert data["message"]["channel"] == "whatsapp"
        assert snd.call_args.args[0] == "972500000000"
        # PII discipline — never the body in the interaction payload.
        payload = logi.call_args.kwargs.get("payload", {})
        assert "booking link" not in str(payload)
        assert payload.get("message_id") == "wamid.ABC"

    def test_window_expired_blocks_send_before_resolving_recipient(self, client):
        cur = _cursor([(1,), None])   # person exists, no client_token collision
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_wa_send_eligibility",
                          return_value={"eligible": False, "reason": "window_expired",
                                        "window_expires_at": "2026-07-01T00:00:00+00:00"}), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient") as resolve, \
             patch.object(main._KAPSO_CHANNEL, "send_text") as snd:
            r = self._post(client, body="hi")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "window_expired"
        resolve.assert_not_called()
        snd.assert_not_called()

    def test_no_whatsapp_address_on_file(self, client):
        cur = _cursor([(1,), None])   # person exists, no client_token collision
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_wa_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value=None), \
             patch.object(main._KAPSO_CHANNEL, "send_text") as snd:
            r = self._post(client, body="hi")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "no_address"
        snd.assert_not_called()

    def test_kapso_failure_records_failed_row_and_reports_send_failed(self, client):
        cur = _cursor([
            (1,),                                        # person exists
            None,                                        # no existing client_token row
            None,                                        # no open opportunity
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_wa_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value="972500000000"), \
             patch.object(main._KAPSO_CHANNEL, "send_text", return_value=None):
            r = self._post(client, body="hi")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "send_failed"
        # The failed row is the LAST execute call — INSERT with status='failed'.
        last_sql = cur.execute.call_args_list[-1].args[0]
        assert "'failed'" in last_sql

    def test_empty_body_is_rejected(self, client):
        cur = _cursor([(1,), None])   # person exists, no client_token collision
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)):
            r = self._post(client, body="   ")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "empty_message"

    def test_repeat_client_token_is_deduped_without_resending(self, client):
        """A retry with the same client_token must not reach Kapso again."""
        sent_at = datetime.datetime(2026, 7, 9, 12, 0, tzinfo=datetime.timezone.utc)
        cur = _cursor([
            (1,),                                                              # person exists
            ("66666666-6666-6666-6666-666666666666", "hi", sent_at, "sent", "wamid.ABC"),
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main._KAPSO_CHANNEL, "send_text") as snd, \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient") as resolve:
            r = self._post(client, body="hi", client_token="tok-repeat")
        data = r.json()
        assert data["status"] == "success"
        assert data["deduped"] is True
        assert data["message"]["provider_message_id"] == "wamid.ABC"
        snd.assert_not_called()
        resolve.assert_not_called()


# ── GET /api/cockpit/thread/{person_id} — Phase 2 additions ───────────────────

class TestThreadGetIncludesEligibilityAndDefaultChannel:
    def test_response_includes_channels_and_default_channel(self, client):
        thread = [
            {"role": "user", "body": "hi", "at": "2026-07-01T00:00:00+00:00", "channel": "whatsapp"},
        ]
        with patch.object(main, "get_db_conn") as gdc, \
             patch.object(main, "_db_person_thread", return_value=thread), \
             patch.object(main, "_wa_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": "2026-07-02T00:00:00+00:00"}):
            gdc.return_value.__enter__.return_value = MagicMock()
            gdc.return_value.__exit__.return_value = False
            r = client.get(f"/api/cockpit/thread/{PID}")
        data = r.json()
        assert data["status"] == "success"
        assert data["channels"]["whatsapp"]["eligible"] is True
        assert data["default_channel"] == "whatsapp"
