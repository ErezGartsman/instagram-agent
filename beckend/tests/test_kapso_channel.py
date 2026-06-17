"""
Kapso BSP transport (Sprint 4 go-live) — unit tests.

All I/O mocked: no Supabase, no Kapso network. Covers the security + parsing
surfaces of the new transport:
  • X-Webhook-Signature verification (bare hex / sha256= prefix / reject / no secret)
  • KapsoChannel send routing (Meta Cloud-API body → _kapso_call with X-API-Key)
  • _kapso_call URL + auth construction
  • defensive inbound extraction across envelope shapes (BSUID-safe)
  • event routing: received → funnel, sent → probe-only, idempotency + mid dedup
  • the POST webhook signature gate + dispatch
"""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

_SECRET = "kapso-whsec-123"


@pytest.fixture
def kapso_client():
    # Isolate module-level state (mirrors tests/test_whatsapp_channel.py).
    main._pool            = None
    main._config_cache    = {}
    main._config_cache_ts = 0.0
    main._rate_store.clear()
    main._wa_seen_mids.clear()
    main._kapso_seen_keys.clear()
    main.settings.kapso_webhook_secret   = _SECRET
    main.settings.kapso_api_key           = "k_test"
    main.settings.kapso_phone_number_id   = "PNID"

    with patch.object(main, "_get_pool") as mock_get_pool:
        mock_get_pool.return_value = MagicMock()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _ksign(raw: bytes, secret: str = _SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _meta_shape(wa_from="972500000000", mid="wamid.K1", body="שלום"):
    return {"entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": wa_from}],
        "messages": [{"from": wa_from, "id": mid, "type": "text",
                      "text": {"body": body}}],
    }}]}]}


def _live_received(phone="972544304272", mid="wamid.LIVE1", body="היי"):
    """The real Kapso inbound shape (confirmed via probe): a single top-level
    'message' + 'conversation', with the BSUID held separately."""
    return {
        "message": {"from": phone, "from_user_id": "IL.2038190160130376",
                    "id": mid, "type": "text", "text": {"body": body},
                    "kapso": {"origin": "cloud_api", "direction": "inbound"}},
        "conversation": {"phone_number": phone,
                         "business_scoped_user_id": "IL.2038190160130376"},
        "is_new_conversation": True, "phone_number_id": "120293527700080",
    }


def _live_sent(origin, to="972544304272", body="אני בודק"):
    """A 'message.sent' echo — origin 'business_app' (Erez's phone) or
    'cloud_api' (our own send)."""
    return {
        "message": {"id": "wamid.S1", "to": to, "from": "972546150955",
                    "type": "text", "text": {"body": body},
                    "kapso": {"origin": origin, "direction": "outbound"}},
        "conversation": {"phone_number": to},
        "phone_number_id": "120293527700080",
    }


# ── _kapso_verify_signature ───────────────────────────────────────────────────

class TestKapsoSignature:
    def test_bare_hex_ok(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_webhook_secret", _SECRET)
        raw = b'{"a":1}'
        assert main._kapso_verify_signature(raw, _ksign(raw)) is True

    def test_sha256_prefixed_ok(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_webhook_secret", _SECRET)
        raw = b'{"a":1}'
        assert main._kapso_verify_signature(raw, "sha256=" + _ksign(raw)) is True

    def test_wrong_signature(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_webhook_secret", _SECRET)
        assert main._kapso_verify_signature(b'{"a":1}', "deadbeef") is False

    def test_missing_header(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_webhook_secret", _SECRET)
        assert main._kapso_verify_signature(b"{}", None) is False

    def test_no_secret_fails_closed(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_webhook_secret", "")
        assert main._kapso_verify_signature(b"{}", "anything") is False


# ── KapsoChannel send routing + _kapso_call ───────────────────────────────────

class TestKapsoSend:
    def test_send_text_routes_through_kapso(self):
        with patch.object(main, "_kapso_call") as call:
            main.KapsoChannel().send_text("972500000000", "hi")
        call.assert_called_once()
        payload = call.call_args[0][0]
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == "972500000000"
        assert payload["type"] == "text"
        assert payload["text"]["body"] == "hi"

    def test_base_channel_still_uses_graph(self):
        # The base channel must remain on the Meta Graph transport (test number).
        with patch.object(main, "_wa_graph_call") as graph, \
             patch.object(main, "_kapso_call") as kapso:
            main.WhatsAppChannel().send_text("972500000000", "hi")
        graph.assert_called_once()
        kapso.assert_not_called()

    def test_kapso_call_url_and_auth(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_api_key", "k_secret")
        monkeypatch.setattr(main.settings, "kapso_phone_number_id", "PN1")
        monkeypatch.setattr(main.settings, "kapso_api_base",
                            "https://api.kapso.ai/meta/whatsapp/v24.0")
        cap = {}

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"messages":[{"id":"x"}]}'

        def fake_urlopen(req, timeout=10):
            cap["url"]     = req.full_url
            cap["headers"] = dict(req.headers)
            cap["body"]    = json.loads(req.data)
            return FakeResp()

        monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(main, "_wa_record_debug", lambda *a, **k: None)
        main._kapso_call({"messaging_product": "whatsapp", "to": "5",
                          "type": "text", "text": {"body": "hi"}})
        assert cap["url"] == "https://api.kapso.ai/meta/whatsapp/v24.0/PN1/messages"
        assert "k_secret" in cap["headers"].values()   # X-API-Key header
        # non-default User-Agent so Cloudflare doesn't 403 us with error 1010
        assert "Mozilla/5.0 (compatible; NEXUS/1.0)" in cap["headers"].values()
        assert cap["body"]["to"] == "5"

    def test_kapso_call_unconfigured_is_noop(self, monkeypatch):
        monkeypatch.setattr(main.settings, "kapso_api_key", "")
        monkeypatch.setattr(main.settings, "kapso_phone_number_id", "")
        assert main._kapso_call({"x": 1}) is None


# ── _kapso_extract_messages (defensive, BSUID-safe) ───────────────────────────

class TestKapsoExtract:
    def test_meta_shape(self):
        assert main._kapso_extract_messages(_meta_shape()) == [
            ("972500000000", "שלום", "wamid.K1")]

    def test_wrapped_data_envelope(self):
        body = {"data": {"messages": [
            {"from": "F1", "id": "m1", "type": "text", "text": {"body": "hi"}}]}}
        assert main._kapso_extract_messages(body) == [("F1", "hi", "m1")]

    def test_bsuid_no_from_uses_wa_id(self):
        body = {"entry": [{"changes": [{"value": {"messages": [
            {"wa_id": "WID", "id": "m", "type": "text", "text": {"body": "yo"}}]}}]}]}
        assert main._kapso_extract_messages(body) == [("WID", "yo", "m")]

    def test_sender_falls_back_to_contacts(self):
        body = {"entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "C1"}],
            "messages": [{"id": "m", "type": "text", "text": {"body": "hey"}}]}}]}]}
        assert main._kapso_extract_messages(body)[0][0] == "C1"

    def test_bare_value(self):
        body = {"messages": [{"from": "F", "id": "m", "type": "text",
                              "text": {"body": "hi"}}]}
        assert main._kapso_extract_messages(body) == [("F", "hi", "m")]

    def test_garbage_is_empty(self):
        assert main._kapso_extract_messages({"random": "noise"}) == []
        assert main._kapso_extract_messages({}) == []

    def test_live_kapso_shape(self):
        assert main._kapso_extract_messages(_live_received()) == [
            ("972544304272", "היי", "wamid.LIVE1")]

    def test_bsuid_prefers_phone_over_token(self):
        # 'from' is the business-scoped user id; the phone is on the conversation.
        body = {"message": {"from": "IL.2038190160130376", "id": "m",
                            "type": "text", "text": {"body": "hi"}},
                "conversation": {"phone_number": "972544304272"}}
        assert main._kapso_extract_messages(body) == [("972544304272", "hi", "m")]


# ── _process_kapso_event routing ──────────────────────────────────────────────

class TestKapsoRouting:
    def test_received_dispatches_to_funnel(self):
        main._kapso_seen_keys.clear()
        main._wa_seen_mids.clear()
        with patch.object(main, "_handle_whatsapp_message") as h:
            main._process_kapso_event("whatsapp.message.received", "i1",
                                      _live_received())
        h.assert_called_once()
        ch, wa_id, text, mid = h.call_args[0]
        assert isinstance(ch, main.KapsoChannel)
        assert (wa_id, text, mid) == ("972544304272", "היי", "wamid.LIVE1")

    def test_sent_business_app_triggers_takeover(self):
        main._kapso_seen_keys.clear()
        with patch.object(main, "_kapso_handle_sent") as ho:
            main._process_kapso_event("whatsapp.message.sent", "s1",
                                      _live_sent("business_app"))
        ho.assert_called_once()

    def test_sent_cloud_api_no_takeover(self):
        main._kapso_seen_keys.clear()
        with patch.object(main, "get_db_conn") as db, \
             patch.object(main, "_handle_whatsapp_message") as h:
            main._process_kapso_event("whatsapp.message.sent", "s2",
                                      _live_sent("cloud_api"))
        db.assert_not_called()
        h.assert_not_called()

    def test_idempotency_dedup(self):
        main._kapso_seen_keys.clear()
        main._wa_seen_mids.clear()
        with patch.object(main, "_wa_record_debug"), \
             patch.object(main, "_handle_whatsapp_message") as h:
            main._process_kapso_event("whatsapp.message.received", "dup",
                                      _meta_shape())
            main._process_kapso_event("whatsapp.message.received", "dup",
                                      _meta_shape())
        assert h.call_count == 1

    def test_mid_dedup_without_idem_key(self):
        main._kapso_seen_keys.clear()
        main._wa_seen_mids.clear()
        with patch.object(main, "_wa_record_debug"), \
             patch.object(main, "_handle_whatsapp_message") as h:
            main._process_kapso_event("whatsapp.message.received", None,
                                      _meta_shape())
            main._process_kapso_event("whatsapp.message.received", None,
                                      _meta_shape())
        assert h.call_count == 1

    def test_status_event_ignored(self):
        main._kapso_seen_keys.clear()
        with patch.object(main, "_wa_record_debug") as rec, \
             patch.object(main, "_handle_whatsapp_message") as h:
            main._process_kapso_event("whatsapp.message.delivered", "i3", {"x": 1})
        rec.assert_not_called()
        h.assert_not_called()


# ── _kapso_handle_sent (Coexistence human-takeover) ───────────────────────────

class TestKapsoTakeover:
    def test_business_app_marks_takeover(self):
        with patch.object(main, "get_db_conn") as gdc, \
             patch.object(main, "_db_get_or_create_channel_session",
                          return_value="sid") as gcs, \
             patch.object(main, "_db_set_session_state") as setstate, \
             patch.object(main, "_db_touch_session"):
            gdc.return_value.__enter__.return_value = MagicMock()
            main._kapso_handle_sent(_live_sent("business_app", to="972544304272"))
            assert gcs.call_args[0][2] == "972544304272"
            assert setstate.call_args[0][2] == main._WA_STATE_TAKEOVER

    def test_cloud_api_is_noop(self):
        with patch.object(main, "get_db_conn") as gdc:
            main._kapso_handle_sent(_live_sent("cloud_api"))
        gdc.assert_not_called()


# ── POST /api/webhooks/kapso ──────────────────────────────────────────────────

class TestKapsoWebhook:
    def test_bad_signature_dropped(self, kapso_client):
        raw = json.dumps(_meta_shape()).encode()
        with patch.object(main, "_process_kapso_event") as p:
            r = kapso_client.post("/api/webhooks/kapso", content=raw, headers={
                "X-Webhook-Signature": "bad",
                "X-Webhook-Event": "whatsapp.message.received",
                "Content-Type": "application/json"})
        assert r.status_code == 200
        p.assert_not_called()

    def test_valid_signature_dispatches(self, kapso_client):
        raw = json.dumps(_meta_shape()).encode()
        with patch.object(main, "_process_kapso_event") as p:
            r = kapso_client.post("/api/webhooks/kapso", content=raw, headers={
                "X-Webhook-Signature": _ksign(raw),
                "X-Webhook-Event": "whatsapp.message.received",
                "X-Idempotency-Key": "abc",
                "Content-Type": "application/json"})
        assert r.status_code == 200
        p.assert_called_once()
        assert p.call_args[0][0] == "whatsapp.message.received"
        assert p.call_args[0][1] == "abc"
