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


# ── Ticket 4.2 — qualification state machine ──────────────────────────────────

def _cfg(key):
    return main._DEFAULT_CONFIG.get(key, "")


def _run_state(text, bot_state, *, classify="AFFIRM", insight="תובנה"):
    """Drive _wa_run_qualification with all boundaries patched; return the
    _wa_send_and_persist mock so tests can assert (reply, new_state)."""
    with patch.object(main, "_get_config", side_effect=_cfg), \
         patch.object(main, "_wa_send_and_persist") as snp, \
         patch.object(main, "_bot_classify_offer_response", return_value=(classify, "")), \
         patch.object(main, "_wa_generate_insight", return_value=insight), \
         patch.object(main.nexus_hooks, "on_funnel_event"):
        main._wa_run_qualification(MagicMock(), "972500000000", "sess-1",
                                   text, bot_state, [])
    snp.assert_called_once()
    args = snp.call_args.args          # (channel, wa_id, session_id, reply, new_state)
    return args[3], args[4]


class TestInsightGuard:
    def test_clean_passes(self):
        assert main._wa_insight_is_clean("נראה שהשכל מבין אבל הלב עוד לא שם") is True

    def test_banned_phrase_caught(self):
        assert main._wa_insight_is_clean("הרבה אנשים במצב שלך מרגישים ככה") is False

    def test_banned_phrase_caught_despite_spacing(self):
        assert main._wa_insight_is_clean("הרבה   אנשים   במצב שלך") is False

    def test_empty_is_not_clean(self):
        assert main._wa_insight_is_clean("") is False


class TestGenerateInsight:
    def test_clean_output_returned(self):
        with patch.object(main, "_get_config", side_effect=_cfg), \
             patch.object(main, "_call_llm", return_value="נראה שאתה תקוע בלופ"):
            assert main._wa_generate_insight("הסיפור שלי") == "נראה שאתה תקוע בלופ"

    def test_banned_output_falls_back(self):
        with patch.object(main, "_get_config", side_effect=_cfg), \
             patch.object(main, "_call_llm", return_value="הרבה אנשים במצב שלך"):
            assert main._wa_generate_insight("x") == _cfg("whatsapp.insight_fallback")

    def test_llm_error_falls_back(self):
        with patch.object(main, "_get_config", side_effect=_cfg), \
             patch.object(main, "_call_llm", side_effect=TimeoutError("slow")):
            assert main._wa_generate_insight("x") == _cfg("whatsapp.insight_fallback")


class TestQualificationFlow:
    def test_entry_sends_opening(self):
        reply, state = _run_state("היי בוט", None)
        assert reply == _cfg("whatsapp.opening")
        assert state == "wa_awaiting_story"

    def test_story_generates_insight_then_bridge(self):
        reply, state = _run_state("אני בלופ", "wa_awaiting_story", insight="INSIGHT_X")
        assert "INSIGHT_X" in reply
        assert _cfg("whatsapp.bridge") in reply
        assert state == "wa_awaiting_interest"

    def test_interest_yes_offers_price(self):
        reply, state = _run_state("כן בשמחה", "wa_awaiting_interest", classify="AFFIRM")
        assert reply == _cfg("whatsapp.price_offer")
        assert state == "wa_offered_price"

    def test_interest_question_still_offers_price(self):
        reply, state = _run_state("כמה זה עולה?", "wa_awaiting_interest", classify="OTHER")
        assert reply == _cfg("whatsapp.price_offer")
        assert state == "wa_offered_price"

    def test_interest_decline_closes(self):
        reply, state = _run_state("לא תודה", "wa_awaiting_interest", classify="DECLINE")
        assert reply == _cfg("whatsapp.decline")
        assert state is None

    def test_price_yes_sends_booking_and_clears(self):
        reply, state = _run_state("מתאים לי", "wa_offered_price", classify="AFFIRM")
        # calendly.url default is empty → lead-in sent without a link
        assert reply == _cfg("whatsapp.booking_leadin")
        assert state is None

    def test_price_decline_closes(self):
        reply, state = _run_state("יקר לי", "wa_offered_price", classify="DECLINE")
        assert reply == _cfg("whatsapp.decline")
        assert state is None


# ── Ticket 4.3 — Calendly → WhatsApp booking confirmation ─────────────────────

class TestBookingConfirmation:
    def test_format_il_datetime(self):
        # 12:00 UTC on 2026-06-17 → Israel summer time (UTC+3) → 15:00.
        out = main._format_il_datetime("2026-06-17T12:00:00Z")
        assert out is not None
        assert "17 ביוני 2026" in out
        assert "בשעה 15:00" in out

    def test_format_il_datetime_bad_input(self):
        assert main._format_il_datetime(None) is None
        assert main._format_il_datetime("") is None
        assert main._format_il_datetime("not-a-date") is None

    def test_send_confirmation_builds_message(self):
        with patch.object(main, "_get_config", side_effect=_cfg), \
             patch.object(main._WHATSAPP_CHANNEL, "send_text") as snd, \
             patch.object(main, "_audit"):
            main._wa_send_booking_confirmation({
                "wa_id": "972500000000",
                "starts_at": "2026-06-17T12:00:00Z",
                "join_url": "https://meet.google.com/abc",
                "reschedule_url": "https://calendly.com/r/x",
            })
        snd.assert_called_once()
        to, msg = snd.call_args.args
        assert to == "972500000000"
        assert _cfg("whatsapp.booking_confirmation") in msg
        assert "בשעה 15:00" in msg
        assert "https://meet.google.com/abc" in msg
        assert "https://calendly.com/r/x" in msg

    def test_send_confirmation_no_wa_id_is_noop(self):
        with patch.object(main._WHATSAPP_CHANNEL, "send_text") as snd:
            main._wa_send_booking_confirmation({})
        snd.assert_not_called()

    def test_booking_link_personalized_with_wa_ref(self):
        cur = MagicMock()
        cur.fetchone.return_value = ("person-1", "ABC234")
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__ = lambda s: s
        conn.__exit__ = MagicMock(return_value=False)
        with patch.object(main, "get_db_conn", return_value=conn), \
             patch.object(main, "_get_config",
                          return_value="https://calendly.com/erez/30min"), \
             patch.object(main.nexus_identity, "attach_phone_identity") as attach:
            out = main._wa_booking_link_and_match("972500000000")
        assert out == "https://calendly.com/erez/30min?utm_content=ABC234"
        attach.assert_called_once()
