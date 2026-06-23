"""
Work Queue Action Loop — POST /api/cockpit/queue/{id}/action.

The DB is mocked (no Supabase, no network) and cockpit auth is bypassed via a
FastAPI dependency override, so these run in CI with no credentials. The point of
these tests is the ENDPOINT CONTRACT the optimistic frontend depends on:
- each action routes to the right stage-machine primitive,
- "done" is a 'handled' cool-off (NOT a close),
- real HTTP status codes (200/400/404/409) so the UI can roll the card back.
"""
import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """TestClient with cockpit auth overridden (no JWT needed)."""
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


def _mock_get_db_conn(row):
    """
    A get_db_conn() replacement whose first cursor.fetchone() returns `row`
    (the opportunities pre-check). __exit__ returns False so raised
    HTTPExceptions propagate instead of being swallowed by the context manager.
    """
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    conn.cursor.return_value = cur
    return MagicMock(return_value=conn)


OPP_ID = "11111111-1111-1111-1111-111111111111"
# Rows match the endpoint's pre-check SELECT: (person_id, stage, closed_at).
OPEN_ROW = (OPP_ID, "captured", None)
CLOSED_ROW = (OPP_ID, "lost", datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))


def _post(client, **body):
    return client.post(f"/api/cockpit/queue/{OPP_ID}/action", json=body)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestQueueAction:
    def test_done_is_a_handled_cooloff_not_a_close(self, client):
        until = datetime.datetime(2026, 6, 26, tzinfo=datetime.timezone.utc)
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_interactions, "snooze_opportunity",
                          return_value=until) as snz, \
             patch.object(main.nexus_interactions, "close_opportunity") as close:
            r = _post(client, type="done")
        assert r.status_code == 200
        data = r.json()
        assert data["closed"] is False                      # stays OPEN
        assert data["snoozed_until"] == until.isoformat()
        assert snz.call_args.kwargs["kind"] == "handled"
        assert snz.call_args.kwargs["hours"] == main._DONE_COOLOFF_HOURS
        close.assert_not_called()                           # Done never closes

    def test_snooze_default_hours(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_interactions, "snooze_opportunity",
                          return_value=None) as snz:
            r = _post(client, type="snooze")
        assert r.status_code == 200
        assert snz.call_args.kwargs["kind"] == "snoozed"
        assert snz.call_args.kwargs["hours"] == main._SNOOZE_DEFAULT_HOURS

    def test_snooze_custom_hours(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_interactions, "snooze_opportunity",
                          return_value=None) as snz:
            r = _post(client, type="snooze", snooze_hours=8)
        assert r.status_code == 200
        assert snz.call_args.kwargs["hours"] == 8

    def test_dismiss_closes_lost(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_interactions, "close_opportunity",
                          return_value=True) as close:
            r = _post(client, type="dismiss")
        assert r.status_code == 200
        assert r.json()["closed"] is True
        assert close.call_args.args[2] == "lost"

    def test_send_routes_to_dispatch(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main, "_dispatch_outreach") as disp:
            r = _post(client, type="send", message="Hi Maya, here's the link")
        assert r.status_code == 200
        assert r.json()["closed"] is False
        disp.assert_called_once()

    def test_unknown_action_400(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)):
            r = _post(client, type="frobnicate")
        assert r.status_code == 400

    def test_missing_opportunity_404(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(None)):
            r = _post(client, type="done")
        assert r.status_code == 404

    def test_act_on_closed_lead_409(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(CLOSED_ROW)):
            r = _post(client, type="send")
        assert r.status_code == 409

    def test_dismiss_closed_is_idempotent_200(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(CLOSED_ROW)):
            r = _post(client, type="dismiss")
        assert r.status_code == 200
        assert r.json()["closed"] is True


class TestSendOutreach:
    """The real _dispatch_outreach flow (Kapso send) — Phase 2."""

    def _send(self, client, message="Hi Maya, here's the link"):
        return client.post(f"/api/cockpit/queue/{OPP_ID}/action",
                           json={"type": "send", "message": message})

    def test_send_success_is_ref_only(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value="972500000000"), \
             patch.object(main._KAPSO_CHANNEL, "send_text",
                          return_value='{"messages":[{"id":"wamid.ABC"}]}') as snd, \
             patch.object(main.nexus_interactions, "log_interaction") as logi:
            r = self._send(client, "Hi Maya, here's the booking link")
        assert r.status_code == 200
        assert r.json()["closed"] is False
        assert snd.call_args.args[0] == "972500000000"          # resolved recipient
        # PII discipline: the body must NOT land in the interaction payload.
        payload = logi.call_args.kwargs.get("payload", {})
        assert "booking link" not in str(payload)
        assert payload.get("message_id") == "wamid.ABC"

    def test_send_no_recipient_422(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value=None):
            r = self._send(client)
        assert r.status_code == 422

    def test_send_kapso_failure_502(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value="972500000000"), \
             patch.object(main._KAPSO_CHANNEL, "send_text", return_value=None):
            r = self._send(client)
        assert r.status_code == 502

    def test_send_empty_message_400(self, client):
        with patch.object(main, "get_db_conn", _mock_get_db_conn(OPEN_ROW)), \
             patch.object(main.nexus_identity, "resolve_whatsapp_recipient",
                          return_value="972500000000"):
            r = self._send(client, "   ")
        assert r.status_code == 400
