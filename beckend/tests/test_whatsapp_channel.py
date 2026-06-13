"""
WhatsApp Cloud API channel (Sprint 4, Ticket 4.1) — unit tests.

All I/O is mocked: no Supabase, no Meta Graph API, no network. Covers the
security-critical and parsing surfaces of the new channel:
  • X-Hub-Signature-256 verification (accept / reject)
  • the GET verify-token handshake (echo challenge / 403)
  • inbound envelope parsing + text extraction + mid dedup + dispatch
"""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

_VERIFY_TOKEN = "verify-token-xyz"
_APP_SECRET   = "app-secret-abc"


@pytest.fixture
def wa_client():
    # Isolate module-level state (mirrors tests/test_main.py's client fixture).
    main._pool            = None
    main._config_cache    = {}
    main._config_cache_ts = 0.0
    main._rate_store.clear()
    main._wa_seen_mids.clear()
    main.settings.whatsapp_verify_token = _VERIFY_TOKEN
    main.settings.whatsapp_app_secret   = _APP_SECRET

    with patch.object(main, "_get_pool") as mock_get_pool:
        mock_get_pool.return_value = MagicMock()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _sign(raw: bytes, secret: str = _APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _text_event(wa_from="972500000000", mid="wamid.TEST1", body="שלום"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "PNID"},
                    "contacts": [{"wa_id": wa_from, "profile": {"name": "Test"}}],
                    "messages": [{
                        "from": wa_from, "id": mid, "timestamp": "0",
                        "type": "text", "text": {"body": body},
                    }],
                },
            }],
        }],
    }


# ── _wa_extract_text ──────────────────────────────────────────────────────────

class TestExtractText:
    def test_text(self):
        assert main._wa_extract_text(
            {"type": "text", "text": {"body": "hi"}}) == "hi"

    def test_interactive_button_reply(self):
        assert main._wa_extract_text({
            "type": "interactive",
            "interactive": {"type": "button_reply",
                            "button_reply": {"id": "YES", "title": "כן"}},
        }) == "YES"

    def test_interactive_list_reply(self):
        assert main._wa_extract_text({
            "type": "interactive",
            "interactive": {"type": "list_reply",
                            "list_reply": {"id": "OPT_A", "title": "A"}},
        }) == "OPT_A"

    def test_button_quick_reply(self):
        assert main._wa_extract_text(
            {"type": "button", "button": {"text": "כן", "payload": "P"}}) == "כן"

    def test_media_returns_empty(self):
        assert main._wa_extract_text(
            {"type": "image", "image": {"id": "x"}}) == ""

    def test_missing_fields_safe(self):
        assert main._wa_extract_text({}) == ""
        assert main._wa_extract_text({"type": "text"}) == ""


# ── _wa_verify_signature ──────────────────────────────────────────────────────

class TestVerifySignature:
    def test_valid(self, monkeypatch):
        monkeypatch.setattr(main.settings, "whatsapp_app_secret", _APP_SECRET)
        raw = b'{"a":1}'
        assert main._wa_verify_signature(raw, _sign(raw)) is True

    def test_wrong_signature(self, monkeypatch):
        monkeypatch.setattr(main.settings, "whatsapp_app_secret", _APP_SECRET)
        assert main._wa_verify_signature(b'{"a":1}', "sha256=deadbeef") is False

    def test_missing_header(self, monkeypatch):
        monkeypatch.setattr(main.settings, "whatsapp_app_secret", _APP_SECRET)
        assert main._wa_verify_signature(b"{}", None) is False


# ── GET verify handshake ──────────────────────────────────────────────────────

class TestVerifyHandshake:
    def test_correct_token_echoes_challenge(self, wa_client):
        r = wa_client.get("/api/webhook/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.verify_token": _VERIFY_TOKEN,
            "hub.challenge": "424242",
        })
        assert r.status_code == 200
        assert r.text == "424242"

    def test_wrong_token_rejected(self, wa_client):
        r = wa_client.get("/api/webhook/whatsapp", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "WRONG",
            "hub.challenge": "424242",
        })
        assert r.status_code == 403


# ── POST webhook: signature gate + parse + dedup + dispatch ────────────────────

class TestWebhookPost:
    def test_bad_signature_silently_dropped(self, wa_client):
        raw = json.dumps(_text_event()).encode()
        with patch.object(main, "_handle_whatsapp_message") as h:
            r = wa_client.post("/api/webhook/whatsapp", content=raw, headers={
                "X-Hub-Signature-256": "sha256=bad",
                "Content-Type": "application/json",
            })
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        h.assert_not_called()

    def test_valid_text_dispatched(self, wa_client):
        raw = json.dumps(
            _text_event(wa_from="972511112222", mid="wamid.A", body="היי")).encode()
        with patch.object(main, "_handle_whatsapp_message") as h:
            r = wa_client.post("/api/webhook/whatsapp", content=raw, headers={
                "X-Hub-Signature-256": _sign(raw),
                "Content-Type": "application/json",
            })
        assert r.status_code == 200
        h.assert_called_once()
        args = h.call_args.args   # (channel, wa_id, text, mid)
        assert args[1] == "972511112222"
        assert args[2] == "היי"
        assert args[3] == "wamid.A"

    def test_status_callback_ignored(self, wa_client):
        body = {"entry": [{"changes": [{"field": "messages", "value": {
            "statuses": [{"id": "wamid.S", "status": "delivered"}]}}]}]}
        raw = json.dumps(body).encode()
        with patch.object(main, "_handle_whatsapp_message") as h:
            r = wa_client.post("/api/webhook/whatsapp", content=raw, headers={
                "X-Hub-Signature-256": _sign(raw),
                "Content-Type": "application/json",
            })
        assert r.status_code == 200
        h.assert_not_called()

    def test_duplicate_mid_dispatched_once(self, wa_client):
        body = _text_event(mid="wamid.DUP")
        msgs = body["entry"][0]["changes"][0]["value"]["messages"]
        msgs.append(dict(msgs[0]))   # same mid twice in one delivery
        raw = json.dumps(body).encode()
        with patch.object(main, "_handle_whatsapp_message") as h:
            wa_client.post("/api/webhook/whatsapp", content=raw, headers={
                "X-Hub-Signature-256": _sign(raw),
                "Content-Type": "application/json",
            })
        assert h.call_count == 1
