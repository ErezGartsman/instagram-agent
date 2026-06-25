"""
P2 WS2/WS4 — Copilot endpoint contract (no network, no DB, no LLM key).

Locks the cockpit UI's two API contracts:
  GET  /api/cockpit/copilot/context  → Person-360 + thread + assembled envelope.
  POST /api/cockpit/copilot/stream   → SSE word-stream (delta events + done).

The DB helpers and _call_llm are patched; _COPILOT_WORD_DELAY_MS is zeroed so
the stream test doesn't sleep. Same CI posture as test_cockpit_action.
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
    {"role": "user",     "body": "שלום",      "at": "2026-06-14T10:00:00+00:00"},
    {"role": "operator", "body": "היי מאיה",  "at": "2026-06-25T19:30:00+00:00"},
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
    yield object()  # helpers are patched, conn never touched


# ── Context endpoint ──────────────────────────────────────────────────────────

def test_context_returns_envelope(client):
    with patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=PERSON), \
         patch.object(main, "_db_whatsapp_thread", return_value=THREAD):
        r = client.get("/api/cockpit/copilot/context", params={"person_id": PID})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
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

def test_stream_emits_deltas_then_done(client):
    """_call_llm returns a fixed two-word draft; delay zeroed; stream is verified."""
    draft_text = "היי מאיה"
    with patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=PERSON), \
         patch.object(main, "_db_whatsapp_thread", return_value=THREAD), \
         patch.object(main, "_call_llm", return_value=draft_text), \
         patch.object(main, "_COPILOT_WORD_DELAY_MS", 0):  # don't sleep in CI
        r = client.post("/api/cockpit/copilot/stream",
                        json={"person_id": PID, "intent": "warm re-engage"})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    deltas = [e for e in events if e["type"] == "delta"]
    done   = [e for e in events if e["type"] == "done"]
    # Two-word draft → two delta events
    assert len(deltas) == 2
    assert "".join(d["text"] for d in deltas).strip() == draft_text
    assert len(done) == 1
    assert done[0]["text"] == draft_text


def test_stream_uses_demo_draft_when_mock_flag_set(client):
    """COPILOT_DEMO_MOCK=1 → nexus_copilot.demo_draft_for() is called instead of _call_llm."""
    with patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=PERSON), \
         patch.object(main, "_db_whatsapp_thread", return_value=THREAD), \
         patch.object(main.settings, "copilot_demo_mock", True), \
         patch.object(main, "_COPILOT_WORD_DELAY_MS", 0):
        r = client.post("/api/cockpit/copilot/stream", json={"person_id": PID})
    assert r.status_code == 200
    events = [
        json.loads(line[len("data: "):])
        for line in r.text.splitlines()
        if line.startswith("data: ")
    ]
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert len(done[0]["text"]) > 5  # got a real draft string


def test_stream_404_when_person_missing(client):
    with patch.object(main, "get_db_conn", _fake_conn), \
         patch.object(main, "_db_person360", return_value=None):
        r = client.post("/api/cockpit/copilot/stream", json={"person_id": PID})
    assert r.status_code == 404
