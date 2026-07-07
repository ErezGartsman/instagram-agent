"""
Tests for the Phase 3 proactive layer:

  1. nexus.dossier pure brains — briefing-item assembly, urgency→trajectory
     mapping, week-chapter grouping + "went quiet" synthesis (no DB, no LLM).
  2. Endpoint contracts — GET /api/cockpit/briefing and
     GET /api/cockpit/person/{id}/dossier against a scripted cursor, asserting
     the exact payload shapes MorningBriefing.tsx / PersonDossierPage.tsx cast.

Same CI posture as test_ai_planner: no network, no DB, no LLM key.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from main import app
from nexus import dossier

PID = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 7, 7, 7, 0)


def day(offset: int, hour: int = 12) -> datetime:
    return datetime(2026, 6, 1, hour, 0) + timedelta(days=offset)


# ── Fakes (mirror test_ai_planner's scripted cursor) ──────────────────────────

class FakeCursor:
    def __init__(self, script):
        self.script = list(script)
        self.data_sql = []
        self._current = None

    def execute(self, sql, params=None):
        self.data_sql.append((sql, params))
        self._current = self.script.pop(0) if self.script else []

    def fetchall(self):
        return self._current if isinstance(self._current, list) else [self._current]

    def fetchone(self):
        if isinstance(self._current, list):
            return self._current[0] if self._current else None
        return self._current

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def rollback(self):
        pass


def conn_ctx(cur):
    @contextmanager
    def _ctx():
        yield FakeConn(cur)
    return _ctx


@pytest.fixture
def client():
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


# ── 1. Briefing assembly ───────────────────────────────────────────────────────

def test_briefing_full_assembly_order_and_shapes():
    items = dossier.build_briefing_items(
        reopened=[{"person_id": PID, "name": "Maya Goren", "gap_days": 21.0}],
        new_leads=["Noa Levi", "Ofir Ben-David"],
        warn_names=["Daniel Roth"],
        breach_names=["Maya Goren"],
    )
    assert [i["tone"] for i in items] == ["signal", "signal", "warn", "danger"]
    for i in items:
        assert set(i) == {"id", "tone", "headline", "detail", "href", "cta"}
    assert items[0]["headline"] == "Maya Goren reopened after 3 weeks of silence"
    assert items[0]["href"] == f"/app/person/{PID}"
    assert items[0]["cta"] == "Open dossier"
    assert "2 new leads" in items[1]["headline"]
    assert "Noa Levi" in items[1]["detail"]
    assert "1 SLA breach approaching" in items[2]["headline"]
    assert "1 lead past their SLA target" in items[3]["headline"]


def test_briefing_quiet_night_is_empty_and_reopens_capped():
    assert dossier.build_briefing_items(
        reopened=[], new_leads=[], warn_names=[], breach_names=[]) == []
    many = [{"person_id": f"p{i}", "name": f"P{i}", "gap_days": 10 + i}
            for i in range(5)]
    items = dossier.build_briefing_items(
        reopened=many, new_leads=[], warn_names=[], breach_names=[])
    assert len(items) == dossier.MAX_REOPENED_ITEMS


def test_briefing_gap_wording_days_vs_weeks():
    def headline(gap):
        return dossier.build_briefing_items(
            reopened=[{"person_id": PID, "name": "X", "gap_days": gap}],
            new_leads=[], warn_names=[], breach_names=[])[0]["headline"]
    assert "10 days of silence" in headline(10.4)
    assert "3 weeks of silence" in headline(21.0)


def test_briefing_names_overflow_counted():
    items = dossier.build_briefing_items(
        reopened=[], new_leads=[f"Lead {i}" for i in range(6)],
        warn_names=[], breach_names=[])
    assert "and 2 more" in items[0]["detail"]


# ── 2. Trajectory ──────────────────────────────────────────────────────────────

def test_trajectory_urgency_mapping_calm_positive():
    pts = dossier.build_trajectory([
        {"urgency": 1, "created_at": day(0)},
        {"urgency": 3, "created_at": day(7)},
        {"urgency": 5, "created_at": day(14)},
        {"urgency": None, "created_at": day(21)},     # no affect signal → skipped
        {"urgency": 9, "created_at": day(28)},        # out of range → clamped to 5
    ])
    assert [p["value"] for p in pts] == [1.0, 0.0, -1.0, -1.0]
    assert pts[0]["label"] == "Jun 1"
    assert pts[0]["at"] == day(0).isoformat()
    assert dossier.build_trajectory([]) == []


# ── 3. Chapters ────────────────────────────────────────────────────────────────

def _s(offset, summary="talked", topic=None, urgency=None, sensitive=False):
    return {"summary": summary, "topic": topic, "emotional_state": None,
            "urgency": urgency, "sensitive": sensitive, "created_at": day(offset)}


def test_chapters_group_by_week_with_topic_titles_and_signals():
    chapters = dossier.build_chapters([
        _s(0, "first contact", topic="אמון בזוגיות", urgency=2),
        _s(2, "opened up", urgency=4),
        _s(8, "went deeper", topic="החלטה"),
    ])
    assert len(chapters) == 2
    wk1, wk2 = chapters
    assert wk1["range"] == "Week of Jun 1"
    assert wk1["title"] == "אמון בזוגיות"                # first topic in the week
    assert "first contact" in wk1["summary"] and "opened up" in wk1["summary"]
    assert "2 conversations" in wk1["signals"]
    assert "urgency 4/5" in wk1["signals"]
    assert wk2["title"] == "החלטה"
    assert wk2["signals"] == ["1 conversation"]          # no urgency → no urgency signal
    for c in chapters:
        assert set(c) == {"id", "range", "title", "summary", "signals", "at"}


def test_chapters_synthesise_went_quiet_for_long_gaps():
    chapters = dossier.build_chapters([
        _s(0, topic="פתיחה"),
        _s(25, topic="חזרה"),                             # 25-day silence in between
    ])
    assert [c["title"] for c in chapters] == ["פתיחה", "Went quiet", "חזרה"]
    quiet = chapters[1]
    assert "No conversations" in quiet["summary"]
    assert quiet["signals"] == ["4 weeks of silence"]
    # A short gap earns no quiet chapter.
    assert [c["title"] for c in dossier.build_chapters(
        [_s(0, topic="a"), _s(10, topic="b")])] == ["a", "b"]


def test_chapters_sensitive_only_week_stays_content_free():
    chapters = dossier.build_chapters([
        _s(0, summary="שיחה רגישה — לא נשמר תוכן.", sensitive=True),
    ])
    assert chapters[0]["title"] == "Sensitive session"
    assert dossier.build_chapters([]) == []
    assert dossier.build_chapters([{"summary": "x", "created_at": None}]) == []


# ── 4. Endpoint contracts ──────────────────────────────────────────────────────

def test_briefing_endpoint_shape(client, monkeypatch):
    cur = FakeCursor([
        [(PID, "Maya Goren", 21.0)],                     # reopened
        [("Noa Levi",)],                                 # new leads
        [("warn", "Daniel Roth"), ("breach", "Maya Goren")],   # sla roster
    ])
    monkeypatch.setattr(main, "get_db_conn", conn_ctx(cur))
    r = client.get("/api/cockpit/briefing")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["compiled_at"]
    tones = [i["tone"] for i in data["items"]]
    assert tones == ["signal", "signal", "warn", "danger"]
    assert data["items"][0]["href"] == f"/app/person/{PID}"


def test_briefing_endpoint_quiet_night(client, monkeypatch):
    cur = FakeCursor([[], [], []])
    monkeypatch.setattr(main, "get_db_conn", conn_ctx(cur))
    data = client.get("/api/cockpit/briefing").json()
    assert data["status"] == "success" and data["items"] == []


def test_dossier_endpoint_full_payload(client, monkeypatch):
    person_row = ("Maya Goren", "BR-1188", day(-20),
                  "She isn't afraid of leaving.",         # essence (pp.summary)
                  {"goal": "decide before the anniversary", "tension": "guilt vs. relief"},
                  [{"fact": "a", "by": "ai"}, {"fact": "b", "by": "operator"}],
                  "captured", "whatsapp", "anxious")
    cur = FakeCursor([
        person_row,
        [("first contact", "אמון", None, 2, False, day(0)),
         ("came back", "חזרה", None, 1, False, day(25))],
        [("outreach_click", NOW)],
    ])
    monkeypatch.setattr(main, "get_db_conn", conn_ctx(cur))
    data = client.get(f"/api/cockpit/person/{PID}/dossier").json()
    assert data["status"] == "success"
    p = data["person"]
    assert set(p) == {"id", "name", "initials", "channel", "handle", "stage",
                      "held_since", "essence", "goal", "tension", "memory_count"}
    assert p["name"] == "Maya Goren" and p["initials"] == "MG"
    assert p["goal"] == "decide before the anniversary"
    assert p["tension"] == "guilt vs. relief"             # attribute beats fallback
    assert p["memory_count"] == 4                         # 2 facts + 2 summaries
    assert [c["title"] for c in data["chapters"]] == ["אמון", "Went quiet", "חזרה"]
    assert [pt["value"] for pt in data["trajectory"]] == [0.5, 1.0]
    assert data["timeline"][0] == {
        "kind": "outreach_click", "label": "Clicked the outreach link",
        "at": NOW.isoformat(),
    }


def test_dossier_endpoint_not_found_and_bad_uuid(client, monkeypatch):
    cur = FakeCursor([None])
    monkeypatch.setattr(main, "get_db_conn", conn_ctx(cur))
    assert client.get(f"/api/cockpit/person/{PID}/dossier").json()["status"] == "error"
    # Bad uuid: rejected before any SQL runs.
    cur2 = FakeCursor([])
    monkeypatch.setattr(main, "get_db_conn", conn_ctx(cur2))
    assert client.get("/api/cockpit/person/not-a-uuid/dossier").json()["status"] == "error"
    assert cur2.data_sql == []
