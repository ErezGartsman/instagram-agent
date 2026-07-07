"""
Tests for nexus.memory formation. Pure helpers (parse/merge/render) need no DB.
The DB-touching run_session_formation is exercised with a FakeConn that records
SQL and serves queued fetch results — proving the crisis governance rule, the
formed path, and graceful failure.
"""

from nexus import memory


# ─── Fake psycopg2 harness ────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 1   # log_interaction reads this to detect dedup no-ops

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append(" ".join(sql.split()))

    def fetchone(self):
        return self._conn.fetchone_queue.pop(0) if self._conn.fetchone_queue else None

    def fetchall(self):
        return self._conn.fetchall_queue.pop(0) if self._conn.fetchall_queue else []


class FakeConn:
    def __init__(self, *, fetchone=None, fetchall=None):
        self.executed = []
        self.fetchone_queue = list(fetchone or [])
        self.fetchall_queue = list(fetchall or [])

    def cursor(self):
        return FakeCursor(self)


def _stmts(conn, prefix):
    return [s for s in conn.executed if s.startswith(prefix)]


# ─── parse_formation ─────────────────────────────────────────────────────────

class TestParseFormation:
    def _full(self, **over):
        base = {"session_summary": "דיברנו על פרידה", "topic": "פרידה",
                "emotional_state": "כאב", "urgency": 9,
                "profile_summary": "אדם שעובר פרידה קשה.",
                "attributes": {"relationship_status": "נפרד", "core_concern": None},
                "facts": ["עבר פרידה", "מתקשה לישון"]}
        base.update(over)
        return base

    def test_happy_path_and_urgency_clamp(self):
        out = memory.parse_formation(self._full())
        assert out["urgency"] == 5                       # 9 clamped
        assert out["topic"] == "פרידה"
        assert out["attributes"] == {"relationship_status": "נפרד"}  # null dropped
        assert out["facts"] == ["עבר פרידה", "מתקשה לישון"]

    def test_drops_string_null_attributes(self):
        out = memory.parse_formation(self._full(attributes={"x": "null", "y": "ערך"}))
        assert out["attributes"] == {"y": "ערך"}

    def test_goal_attribute_flows_through(self):
        out = memory.parse_formation(self._full(
            attributes={"goal": "להחליט אם להישאר", "core_concern": None}))
        assert out["attributes"]["goal"] == "להחליט אם להישאר"
        assert "core_concern" not in out["attributes"]   # null dropped

    def test_caps_facts_to_four(self):
        out = memory.parse_formation(self._full(facts=["a", "b", "c", "d", "e", "f"]))
        assert len(out["facts"]) == 4

    def test_bad_urgency_becomes_none(self):
        out = memory.parse_formation(self._full(urgency="high"))
        assert out["urgency"] is None

    def test_empty_returns_none(self):
        assert memory.parse_formation({"session_summary": "", "profile_summary": ""}) is None
        assert memory.parse_formation("not a dict") is None


# ─── merge_profile ───────────────────────────────────────────────────────────

class TestMergeProfile:
    def _formation(self, **over):
        base = {"profile_summary": "סיכום מעודכן", "attributes": {"core_concern": "חרדה"},
                "facts": ["עובדה חדשה"]}
        base.update(over)
        return base

    def test_new_profile_from_scratch(self):
        merged = memory.merge_profile(None, self._formation(), session_id="s1")
        assert merged["summary"] == "סיכום מעודכן"
        assert merged["attributes"] == {"core_concern": "חרדה"}
        assert merged["facts"] == [{"fact": "עובדה חדשה", "by": "ai", "session_id": "s1"}]
        assert merged["version"] == 1

    def test_operator_facts_are_never_dropped(self):
        existing = {"summary": "ישן", "attributes": {"relationship_status": "נשוי"},
                    "facts": [{"fact": "סיפר על הילדים", "by": "operator"},
                              {"fact": "עובדת AI ישנה", "by": "ai"}],
                    "version": 3}
        merged = memory.merge_profile(existing, self._formation(), session_id="s2")
        kinds = {f["by"] for f in merged["facts"]}
        texts = {f["fact"] for f in merged["facts"]}
        assert "operator" in kinds
        assert "סיפר על הילדים" in texts          # operator fact preserved
        assert "עובדה חדשה" in texts              # new AI fact added
        assert merged["attributes"]["relationship_status"] == "נשוי"  # prior key kept
        assert merged["attributes"]["core_concern"] == "חרדה"         # new key merged
        assert merged["version"] == 4                                 # bumped

    def test_attributes_new_value_wins(self):
        existing = {"attributes": {"core_concern": "ישן"}, "facts": [], "version": 1}
        merged = memory.merge_profile(existing, self._formation(), session_id="s3")
        assert merged["attributes"]["core_concern"] == "חרדה"

    def test_goal_merges_and_updates(self):
        existing = {"attributes": {"goal": "ישן", "relationship_status": "נשוי"},
                    "facts": [], "version": 1}
        merged = memory.merge_profile(
            existing, self._formation(attributes={"goal": "לשקם אמון"}), session_id="s5")
        assert merged["attributes"]["goal"] == "לשקם אמון"             # new goal wins
        assert merged["attributes"]["relationship_status"] == "נשוי"   # prior key kept

    def test_ai_fact_dedup(self):
        existing = {"facts": [{"fact": "עובדה חדשה", "by": "ai"}], "version": 1}
        merged = memory.merge_profile(existing, self._formation(), session_id="s4")
        assert sum(1 for f in merged["facts"] if f["fact"] == "עובדה חדשה") == 1


# ─── formation prompt ────────────────────────────────────────────────────────

class TestFormationPrompt:
    def test_prompt_requests_goal_attribute(self):
        # The extraction is wired: the LLM is explicitly asked for attributes.goal,
        # which the Person-360 right pane (cockpit Work Queue) reads.
        assert "goal" in memory.FORMATION_PROMPT
        assert "attributes.goal" in memory.FORMATION_PROMPT

    def test_prompt_requests_tension_attribute(self):
        # Phase 3: tension is extracted explicitly (the queue's emotional_state
        # fallback stays, but the attribute is the first-class source).
        assert "attributes.tension" in memory.FORMATION_PROMPT

    def test_prompt_mandates_english_goal_tension_essence(self):
        # Phase 3 directive: Goal / Tension / Essence (profile_summary) are
        # English-only regardless of input language — they power the English
        # cockpit. The episodic fields stay Hebrew for the recall block.
        assert "ONLY in English" in memory.FORMATION_PROMPT
        assert "regardless of the input language" in memory.FORMATION_PROMPT
        assert "ENGLISH sentences" in memory.FORMATION_PROMPT   # profile_summary
        assert "Hebrew sentences" in memory.FORMATION_PROMPT    # session_summary stays


# ─── render helpers ──────────────────────────────────────────────────────────

class TestRender:
    def test_existing_empty_is_placeholder(self):
        assert "היכרות הראשונה" in memory.render_existing(None)
        assert "היכרות הראשונה" in memory.render_existing({"summary": "", "facts": []})

    def test_existing_includes_summary_and_facts(self):
        r = memory.render_existing({"summary": "אדם בפרידה",
                                    "facts": [{"fact": "עבר פרידה"}]})
        assert "אדם בפרידה" in r
        assert "עבר פרידה" in r

    def test_transcript_renders_roles(self):
        t = memory.render_transcript([("user", "שלום"), ("assistant", "היי")])
        assert "משתמש: שלום" in t
        assert "עוזר: היי" in t


# ─── build_recall_block (Hook F) ─────────────────────────────────────────────

class TestBuildRecallBlock:
    def test_full_block_contains_profile_facts_summaries_and_guardrails(self):
        conn = FakeConn(
            fetchone=[("p-1",),                                  # session stamp
                      ("אדם שעובר פרידה.",                        # profile summary
                       [{"fact": "עבר פרידה", "by": "ai"},
                        {"fact": "מתקשה לישון", "by": "operator"}])],
            fetchall=[[("שיחה על געגוע",), ("שיחה על ביטחון",)]])
        block = memory.build_recall_block(conn, session_id="s-1")

        assert "רקע פנימי" in block
        assert "אדם שעובר פרידה." in block
        assert "עבר פרידה" in block and "מתקשה לישון" in block
        assert "שיחה על געגוע" in block and "שיחה על ביטחון" in block
        assert "הנחיות זיכרון" in block          # guardrails ride inside
        assert block.endswith("\n\n")
        # M4: sensitive sessions are excluded at the SQL level.
        assert any("sensitive = FALSE" in s for s in conn.executed)

    def test_unstamped_session_returns_empty(self):
        conn = FakeConn(fetchone=[(None,)])
        assert memory.build_recall_block(conn, session_id="s-2") == ""

    def test_no_memory_yet_returns_empty(self):
        conn = FakeConn(fetchone=[("p-3",), None], fetchall=[[]])
        assert memory.build_recall_block(conn, session_id="s-3") == ""

    def test_db_failure_returns_empty_never_raises(self):
        class BrokenConn:
            def cursor(self):
                raise RuntimeError("db down")
        assert memory.build_recall_block(BrokenConn(), session_id="s-4") == ""


# ─── run_session_formation ───────────────────────────────────────────────────

_FORMATION_JSON = {
    "session_summary": "דיברנו על קושי בזוגיות", "topic": "זוגיות",
    "emotional_state": "תסכול", "urgency": 3,
    "profile_summary": "אדם שמתמודד עם קושי בזוגיות.",
    "attributes": {"core_concern": "תקשורת"}, "facts": ["מתקשה לתקשר"],
}


class TestRunSessionFormation:
    def test_crisis_session_stores_neutral_and_no_profile(self):
        conn = FakeConn(fetchall=[[("user", "אני רוצה למות")]])
        out = memory.run_session_formation(
            conn, session_id="s1", person_id="p1", channel="instagram",
            call_llm=lambda p: (_ for _ in ()).throw(AssertionError("LLM must not run")),
            parse_json=lambda r: {}, is_crisis_fn=lambda t: True,
            model_version="m")
        assert out == "sensitive"
        ins = _stmts(conn, "INSERT INTO session_summaries")
        assert ins                                   # a summary row was written
        assert not _stmts(conn, "INSERT INTO person_profile")   # but NO profile
        assert _stmts(conn, "INSERT INTO interactions")         # formation_run logged

    def test_formed_writes_summary_profile_and_interaction(self):
        # fetchall: messages; fetchone: existing profile lookup → None (new person)
        conn = FakeConn(fetchall=[[("user", "יש לי קושי"), ("assistant", "ספר לי")]],
                        fetchone=[None])
        out = memory.run_session_formation(
            conn, session_id="s2", person_id="p2", channel="telegram",
            call_llm=lambda p: "raw-json", parse_json=lambda r: dict(_FORMATION_JSON),
            is_crisis_fn=lambda t: False, model_version="m")
        assert out == "formed"
        assert _stmts(conn, "INSERT INTO session_summaries")
        assert _stmts(conn, "INSERT INTO person_profile")
        assert _stmts(conn, "INSERT INTO interactions")

    def test_parse_failure_writes_nothing(self):
        conn = FakeConn(fetchall=[[("user", "א"), ("user", "ב")]], fetchone=[None])
        out = memory.run_session_formation(
            conn, session_id="s3", person_id="p3", channel="telegram",
            call_llm=lambda p: "raw", parse_json=lambda r: {},   # → parse_formation None
            is_crisis_fn=lambda t: False, model_version="m")
        assert out == "failed"
        assert not _stmts(conn, "INSERT INTO session_summaries")

    def test_empty_session_is_skipped(self):
        conn = FakeConn(fetchall=[[]])
        out = memory.run_session_formation(
            conn, session_id="s4", person_id="p4", channel="telegram",
            call_llm=lambda p: "x", parse_json=lambda r: {},
            is_crisis_fn=lambda t: False, model_version="m")
        assert out == "empty"
        assert conn.executed == [
            "SELECT role, content FROM messages WHERE session_id = %s ORDER BY created_at"
        ]
