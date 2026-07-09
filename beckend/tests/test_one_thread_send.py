"""
One Thread — send-from-cockpit (WhatsApp Phase 2, Instagram + Telegram Phase 3).

Covers four layers, no Supabase/network:
  1. _channel_send_eligibility — WhatsApp/Instagram's 24h free-form window vs.
     Telegram's no-window rule, pure DB read.
  2. resolve_channel_recipient  — dispatches to resolve_whatsapp_recipient for
     WhatsApp, a direct person_identity lookup for Instagram/Telegram.
  3. _resolve_default_channel   — 'reply to last inbound', pure Python.
  4. POST /api/cockpit/thread/{person_id}/send — the composer's endpoint
     contract across all three channels: always HTTP 200, {status, reason_code,
     detail} on any block, idempotent via client_token, and it must NEVER
     attempt a send when the channel isn't supported or eligibility says no.

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


# ── _channel_send_eligibility ─────────────────────────────────────────────────

class TestChannelSendEligibility:
    def test_whatsapp_within_24h_is_eligible(self):
        last_inbound = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        cur = _cursor([(last_inbound,)])
        conn = _conn_returning(cur)
        result = main._channel_send_eligibility(conn, PID, "whatsapp")
        assert result["eligible"] is True
        assert result["reason"] is None
        assert result["window_expires_at"] is not None

    def test_whatsapp_past_24h_is_window_expired(self):
        last_inbound = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)
        cur = _cursor([(last_inbound,)])
        conn = _conn_returning(cur)
        result = main._channel_send_eligibility(conn, PID, "whatsapp")
        assert result["eligible"] is False
        assert result["reason"] == "window_expired"

    def test_instagram_past_24h_is_also_window_expired(self):
        """Instagram shares WhatsApp's 24h Meta customer-service window."""
        last_inbound = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=30)
        cur = _cursor([(last_inbound,)])
        conn = _conn_returning(cur)
        result = main._channel_send_eligibility(conn, PID, "instagram")
        assert result["eligible"] is False
        assert result["reason"] == "window_expired"

    def test_telegram_has_no_window_even_after_a_year(self):
        """Telegram bots may message anyone who has ever started a conversation —
        no session-expiry concept, unlike WhatsApp/Instagram."""
        last_inbound = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=365)
        cur = _cursor([(last_inbound,)])
        conn = _conn_returning(cur)
        result = main._channel_send_eligibility(conn, PID, "telegram")
        assert result["eligible"] is True
        assert result["reason"] is None
        assert result["window_expires_at"] is None

    def test_never_messaged_is_no_inbound_yet_regardless_of_channel(self):
        for channel in ("whatsapp", "instagram", "telegram"):
            cur = _cursor([(None,)])
            conn = _conn_returning(cur)
            result = main._channel_send_eligibility(conn, PID, channel)
            assert result["eligible"] is False
            assert result["reason"] == "no_inbound_yet"
            assert result["window_expires_at"] is None


# ── resolve_channel_recipient ──────────────────────────────────────────────────

class TestResolveChannelRecipient:
    def test_whatsapp_delegates_to_resolve_whatsapp_recipient(self):
        conn = MagicMock()
        with patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value="972500000000") as resolve_wa:
            result = main.nexus_identity.resolve_channel_recipient(conn, PID, "whatsapp")
        assert result == "972500000000"
        resolve_wa.assert_called_once_with(conn, PID)

    def test_instagram_reads_person_identity_directly(self):
        cur = _cursor([("igsid-123",)])
        conn = _conn_returning(cur)
        result = main.nexus_identity.resolve_channel_recipient(conn, PID, "instagram")
        assert result == "igsid-123"

    def test_telegram_reads_person_identity_directly(self):
        cur = _cursor([("chat-456",)])
        conn = _conn_returning(cur)
        result = main.nexus_identity.resolve_channel_recipient(conn, PID, "telegram")
        assert result == "chat-456"

    def test_no_identity_returns_none(self):
        cur = _cursor([None])
        conn = _conn_returning(cur)
        assert main.nexus_identity.resolve_channel_recipient(conn, PID, "instagram") is None


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
        assert main._resolve_default_channel(messages) == "whatsapp"

    def test_falls_back_to_last_message_when_no_user_role_present(self):
        messages = [{"role": "assistant", "channel": "telegram", "at": "2026-07-01T00:00:00"}]
        assert main._resolve_default_channel(messages) == "telegram"


# ── POST /api/cockpit/thread/{person_id}/send ─────────────────────────────────

class TestThreadSendEndpoint:
    def _post(self, client, **body):
        body.setdefault("client_token", "tok-1")
        return client.post(f"/api/cockpit/thread/{PID}/send", json=body)

    def test_unsupported_channel_is_rejected_before_touching_db(self, client):
        with patch.object(main, "get_db_conn") as gdc:
            r = self._post(client, body="hi", channel="email")
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

    def test_successful_whatsapp_send_is_ref_only_and_returns_message(self, client):
        sent_at = datetime.datetime(2026, 7, 9, 12, 0, tzinfo=datetime.timezone.utc)
        cur = _cursor([
            (1,),                                        # person exists
            None,                                        # no existing client_token row
            ("44444444-4444-4444-4444-444444444444",),   # open opportunity
            ("55555555-5555-5555-5555-555555555555", sent_at),  # INSERT RETURNING
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_channel_recipient",
                          return_value="972500000000"), \
             patch.object(main._KAPSO_CHANNEL, "send_text",
                          return_value='{"messages":[{"id":"wamid.ABC"}]}') as snd, \
             patch.object(main.nexus_interactions, "log_interaction") as logi:
            r = self._post(client, body="Hi Maya, here's the booking link", channel="whatsapp")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["message"]["provider_message_id"] == "wamid.ABC"
        assert data["message"]["role"] == "operator"
        assert data["message"]["channel"] == "whatsapp"
        assert snd.call_args.args[0] == "972500000000"
        payload = logi.call_args.kwargs.get("payload", {})
        assert "booking link" not in str(payload)   # PII discipline
        assert payload.get("message_id") == "wamid.ABC"

    def test_successful_instagram_send_extracts_message_id_from_graph_response(self, client):
        sent_at = datetime.datetime(2026, 7, 9, 12, 0, tzinfo=datetime.timezone.utc)
        cur = _cursor([
            (1,), None, None,   # person exists, no client_token collision, no open opp
            ("66666666-6666-6666-6666-666666666666", sent_at),  # INSERT RETURNING
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_channel_recipient",
                          return_value="igsid-999"), \
             patch.object(main._INSTAGRAM_CHANNEL, "send_text",
                          return_value='{"recipient_id":"igsid-999","message_id":"mid.XYZ"}') as snd:
            r = self._post(client, body="hi from IG", channel="instagram")
        data = r.json()
        assert data["status"] == "success"
        assert data["message"]["channel"] == "instagram"
        assert data["message"]["provider_message_id"] == "mid.XYZ"
        assert snd.call_args.args[0] == "igsid-999"

    def test_successful_telegram_send_uses_int_message_id_directly(self, client):
        sent_at = datetime.datetime(2026, 7, 9, 12, 0, tzinfo=datetime.timezone.utc)
        cur = _cursor([
            (1,), None, None,   # person exists, no client_token collision, no open opp
            ("77777777-7777-7777-7777-777777777777", sent_at),  # INSERT RETURNING
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_channel_recipient",
                          return_value="chat-42"), \
             patch.object(main._TELEGRAM_CHANNEL, "send_text", return_value=987654) as snd:
            r = self._post(client, body="hi from TG", channel="telegram")
        data = r.json()
        assert data["status"] == "success"
        assert data["message"]["channel"] == "telegram"
        assert data["message"]["provider_message_id"] == "987654"
        assert snd.call_args.args[0] == "chat-42"

    def test_window_expired_blocks_send_before_resolving_recipient(self, client):
        cur = _cursor([(1,), None])   # person exists, no client_token collision
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": False, "reason": "window_expired",
                                        "window_expires_at": "2026-07-01T00:00:00+00:00"}), \
             patch.object(main.nexus_identity, "resolve_channel_recipient") as resolve, \
             patch.object(main._KAPSO_CHANNEL, "send_text") as snd:
            r = self._post(client, body="hi")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "window_expired"
        resolve.assert_not_called()
        snd.assert_not_called()

    def test_no_address_on_file(self, client):
        cur = _cursor([(1,), None])   # person exists, no client_token collision
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_channel_recipient",
                          return_value=None), \
             patch.object(main._KAPSO_CHANNEL, "send_text") as snd:
            r = self._post(client, body="hi")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "no_address"
        snd.assert_not_called()

    def test_provider_failure_records_failed_row_and_reports_send_failed(self, client):
        cur = _cursor([
            (1,),                                        # person exists
            None,                                        # no existing client_token row
            None,                                        # no open opportunity
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": None}), \
             patch.object(main.nexus_identity, "resolve_channel_recipient",
                          return_value="972500000000"), \
             patch.object(main._KAPSO_CHANNEL, "send_text", return_value=None):
            r = self._post(client, body="hi")
        data = r.json()
        assert data["status"] == "error"
        assert data["reason_code"] == "send_failed"
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
        """A retry with the same client_token must not reach the provider again."""
        sent_at = datetime.datetime(2026, 7, 9, 12, 0, tzinfo=datetime.timezone.utc)
        cur = _cursor([
            (1,),                                                                     # person exists
            ("88888888-8888-8888-8888-888888888888", "hi", sent_at, "sent", "wamid.ABC", "whatsapp"),
        ])
        conn = _conn_returning(cur)
        with patch.object(main, "get_db_conn", _get_db_conn_returning(conn)), \
             patch.object(main._KAPSO_CHANNEL, "send_text") as snd, \
             patch.object(main.nexus_identity, "resolve_channel_recipient") as resolve:
            r = self._post(client, body="hi", client_token="tok-repeat")
        data = r.json()
        assert data["status"] == "success"
        assert data["deduped"] is True
        assert data["message"]["provider_message_id"] == "wamid.ABC"
        snd.assert_not_called()
        resolve.assert_not_called()


# ── GET /api/cockpit/thread/{person_id} — per-channel eligibility ─────────────

class TestThreadGetIncludesEligibilityAndDefaultChannel:
    def test_response_includes_all_three_channels_and_default_channel(self, client):
        thread = [
            {"role": "user", "body": "hi", "at": "2026-07-01T00:00:00+00:00", "channel": "whatsapp"},
        ]
        with patch.object(main, "get_db_conn") as gdc, \
             patch.object(main, "_db_person_thread", return_value=thread), \
             patch.object(main, "_channel_send_eligibility",
                          return_value={"eligible": True, "reason": None,
                                        "window_expires_at": "2026-07-02T00:00:00+00:00"}):
            gdc.return_value.__enter__.return_value = MagicMock()
            gdc.return_value.__exit__.return_value = False
            r = client.get(f"/api/cockpit/thread/{PID}")
        data = r.json()
        assert data["status"] == "success"
        assert set(data["channels"].keys()) == {"whatsapp", "instagram", "telegram"}
        assert data["channels"]["whatsapp"]["eligible"] is True
        assert data["default_channel"] == "whatsapp"
