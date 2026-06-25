"""
P2 WS2 — Copilot endpoint contract (no network, no DB, no key).

Locks what the cockpit UI depends on:
- GET  /api/cockpit/copilot/context → Person-360 + thread + assembled envelope,
  plus `available` reflecting whether a Claude key is configured.
- POST /api/cockpit/copilot/stream → 503 when unconfigured; otherwise SSE with
  `delta` events then a terminal `done` carrying the full draft.

The DB helpers and the Claude stream are patched, so this runs in CI with no
credentials — same posture as test_cockpit_action.
"""
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

PERSON = {
    "name": "Maya Goren", "channel": "whatsapp", "handle": "BR-1188",
    "stage": "captured", "essence": "test essence", "goal": "decide",
    "tension": "guilt vs relief", "emotional_state": "anxious", "topic": "separation",
}
THREAD = [
    {"role": "user", "body": "שלום", "at": "2026-06-14T10:00:00+00:00"},
    {"role": "operator", "body": "היי מאיה", "at": "2026-06-25T19:30:00+00:00"},
]
PID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


@contextmanager
def _fake_conn():
    yield object()  # the helpers are patched, so the conn itself is never touched


# ── Context endpoint ──────────────────────────────────────────────────────────

def test_context_returns_envelope_and_availability(client):
    with patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=PERSON), \
         patch.object(main, "_db_whatsapp_thread", return_value=THREAD), \
         patch.object(main.nexus_copilot, "is_available", return_value=False):
        r = client.get("/api/cockpit/copilot/context", params={"person_id": PID})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["available"] is False
    assert data["person"]["name"] == "Maya Goren"
    assert len(data["thread"]) == 2
    assert "Maya Goren" in data["envelope"]
    assert "היי מאיה" in data["envelope"]


def test_context_404_when_person_missing(client):
    with patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=None):
        r = client.get("/api/cockpit/copilot/context", params={"person_id": PID})
    assert r.status_code == 404


# ── Stream endpoint ───────────────────────────────────────────────────────────

def test_stream_503_when_copilot_unconfigured(client):
    with patch.object(main.nexus_copilot, "is_available", return_value=False):
        r = client.post("/api/cockpit/copilot/stream", json={"person_id": PID})
    assert r.status_code == 503


def test_stream_emits_deltas_then_done(client):
    def _fake_stream(person, thread, intent=None):
        assert person["name"] == "Maya Goren"   # context was gathered + passed through
        yield "היי "
        yield "מאיה"

    with patch.object(main.nexus_copilot, "is_available", return_value=True), \
         patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=PERSON), \
         patch.object(main, "_db_whatsapp_thread", return_value=THREAD), \
         patch.object(main.nexus_copilot, "stream_reply_draft", _fake_stream):
        r = client.post("/api/cockpit/copilot/stream",
                        json={"person_id": PID, "intent": "warm re-engage"})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[len("data: "):])
              for line in r.text.splitlines() if line.startswith("data: ")]
    deltas = [e for e in events if e["type"] == "delta"]
    done = [e for e in events if e["type"] == "done"]
    assert [d["text"] for d in deltas] == ["היי ", "מאיה"]
    assert len(done) == 1
    assert done[0]["text"] == "היי מאיה"   # full draft reassembled


def test_stream_404_when_person_missing(client):
    with patch.object(main.nexus_copilot, "is_available", return_value=True), \
         patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=None):
        r = client.post("/api/cockpit/copilot/stream", json={"person_id": PID})
    assert r.status_code == 404
