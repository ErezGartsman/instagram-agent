"""
Eval harness for the cockpit AI query planner (nexus/ai_planner.py + the
rewired POST /api/cockpit/ai/chat).

Certifies the planner on ANY model by testing every deterministic layer with
the LLM mocked:

  1. Registry + arg validation — injection attempts neutralised by
     construction, enums/ints/shortcodes enforced, unknown args dropped.
  2. Plan parsing — malformed planner output raises PlanError (→ legacy
     fallback), valid plans are typed/capped/deduped.
  3. Tool execution — scripted fake cursor; asserts tenant_id binding, LIMIT
     bounds, and the FROZEN context_data shapes GlowingAiAssistant.tsx casts.
  4. Endpoint regressions for the "context tunnel vision" bug:
       • plain-text "Show pipeline overview" with EMPTY chips → funnel tool
       • plain-text "Community metrics" → community tool
     plus: planner garbage → legacy router fallback, and the
     ai_chat.planner_enabled kill switch.
  5. Opt-in live smoke (set NEXUS_LIVE_LLM_EVALS=1) — runs the real planner
     prompt against the configured LLM and asserts the plan parses. Use this
     to certify a model swap (Gemini Flash → anything) without touching code.

No network, no DB, no LLM key needed for 1-4 (same CI posture as
test_cockpit_copilot_endpoints).
"""
import os
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app
from nexus import ai_planner as ap

PID = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 7, 5, 12, 0)

# ── Fakes ─────────────────────────────────────────────────────────────────────

_CONTROL_PREFIXES = ("SAVEPOINT", "ROLLBACK", "RELEASE", "SET ")


class FakeCursor:
    """Feeds scripted results to data statements; records every (sql, params)."""

    def __init__(self, script):
        self.script = list(script)
        self.executed = []          # every call, including control statements
        self.data_sql = []          # only real data statements
        self._current = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.strip().upper().startswith(_CONTROL_PREFIXES):
            return
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


def run(tool_name, script, args=None, get_config=lambda k: "2500"):
    """Validate args + run one tool against a scripted cursor."""
    tool = ap.TOOLS[tool_name]
    clean = ap.validate_args(tool, args or {})
    cur = FakeCursor(script)
    res = ap.run_tool(ap.PlanStep(tool_name, clean), cur, ap.DEFAULT_TENANT_ID, get_config)
    return res, cur


@pytest.fixture
def client():
    app.dependency_overrides[main.require_cockpit_user] = lambda: {
        "email": "erez@example.com", "sub": "user-1",
    }
    yield TestClient(app)
    app.dependency_overrides.pop(main.require_cockpit_user, None)


# ── 1. Registry + arg validation ──────────────────────────────────────────────

def test_registry_names_and_descriptions():
    assert len(ap.TOOLS) >= 13
    for name, tool in ap.TOOLS.items():
        assert tool.name == name
        assert tool.description.strip()
        for arg_name, spec in tool.args.items():
            assert spec.kind in ("enum", "str", "int", "shortcode"), (name, arg_name)


def test_planner_prompt_renders_full_catalog():
    prompt = ap.build_planner_prompt("hello", [], [])
    for name in ap.TOOLS:
        assert name in prompt
    assert '"plan"' in prompt


def test_enum_arg_rejects_bad_stage():
    tool = ap.TOOLS["stage_pipeline"]
    with pytest.raises(ap.PlanError):
        ap.validate_args(tool, {"stage": "robert'); DROP TABLE opportunities;--"})
    assert ap.validate_args(tool, {"stage": " Qualified "}) == {"stage": "qualified"}


def test_str_arg_neutralises_injection_and_wildcards():
    tool = ap.TOOLS["sla_lead_lookup"]
    clean = ap.validate_args(tool, {"name": "Dana%'; DROP TABLE person;--_x" + "A" * 200})
    val = clean["name"]
    assert "%" not in val
    assert len(val) <= ap.MAX_ARG_STR_LEN
    # The hostile value only ever travels as a BOUND PARAM — prove it:
    res, cur = run("sla_lead_lookup", [None], {"name": "'; DROP TABLE person;--"})
    for sql, params in cur.data_sql:
        assert "DROP TABLE" not in sql
        assert "%(f)s" in sql or "%(t)s" in sql        # placeholders, not splices
    assert "no matching" in res.context_block


def test_str_arg_keeps_underscores():
    # Ref codes / usernames contain underscores — they must survive cleaning
    # (underscore is a benign LIKE single-char wildcard and is always bound).
    clean = ap.validate_args(ap.TOOLS["sla_lead_lookup"], {"name": "lead_42"})
    assert clean["name"] == "lead_42"


def test_int_arg_clamped():
    tool = ap.TOOLS["top_posts"]
    assert ap.validate_args(tool, {"limit": 9999})["limit"] == 10
    assert ap.validate_args(tool, {"limit": -5})["limit"] == 1
    assert ap.validate_args(tool, {})["limit"] == 5
    with pytest.raises(ap.PlanError):
        ap.validate_args(tool, {"limit": "ten; DROP"})


def test_shortcode_arg_regex():
    tool = ap.TOOLS["post_engagement"]
    assert ap.validate_args(tool, {"shortcode": "DKtq3xZjWm"})["shortcode"] == "DKtq3xZjWm"
    for bad in ("a", "has space", "quote'x", "x" * 40, None):
        with pytest.raises(ap.PlanError):
            ap.validate_args(tool, {"shortcode": bad})


def test_required_arg_missing_raises():
    with pytest.raises(ap.PlanError):
        ap.validate_args(ap.TOOLS["person_360"], {})


# ── 2. Plan parsing (defensive) ───────────────────────────────────────────────

def test_parse_plan_rejects_non_plan_shapes():
    for bad in (None, [], "text", {"answer": "42"}, {"plan": "funnel_overview"}):
        with pytest.raises(ap.PlanError):
            ap.parse_plan(bad)


def test_parse_plan_rejects_all_unknown_tools():
    with pytest.raises(ap.PlanError):
        ap.parse_plan({"plan": [{"tool": "drop_all_tables", "args": {}}]})


def test_parse_plan_keeps_valid_drops_invalid():
    steps = ap.parse_plan({"plan": [
        {"tool": "made_up", "args": {}},
        {"tool": "funnel_overview", "args": {}},
        {"tool": "stage_pipeline", "args": {"stage": "not-a-stage"}},
    ]})
    assert [s.tool for s in steps] == ["funnel_overview"]


def test_parse_plan_empty_is_valid_and_caps_and_dedupes():
    assert ap.parse_plan({"plan": []}) == []
    many = {"plan": [{"tool": "funnel_overview", "args": {}}] * 10}
    assert len(ap.parse_plan(many)) == 1          # deduped
    varied = {"plan": [
        {"tool": "funnel_overview"}, {"tool": "sla_overview"},
        {"tool": "community_metrics"}, {"tool": "follower_growth"},
        {"tool": "top_posts"},                     # 5th — over the cap
    ]}
    assert len(ap.parse_plan(varied)) == ap.MAX_TOOLS_PER_PLAN


# ── 3. Tool execution — tenant binding, LIMIT bounds, frozen ctx shapes ───────

FM_ROW = ("engaged", "qualified", 10, 50.0, 24.0)
HAPPY = {
    "funnel_overview":      ([[FM_ROW], [("engaged", 3), ("qualified", 2)], (12,)], {}),
    "stage_pipeline":       ([(3, 12.5)], {"stage": "qualified"}),
    "stage_velocity":       ([(24.0, 20.0, 50.0)], {"stage": "engaged"}),
    "sla_overview":         ([[("breach", 2), ("ok", 1)],
                              [(PID, "Dana Levi", "captured", 80.0, 72, "breach")],
                              [(PID, "972555000")]], {}),
    "sla_lead_lookup":      ([("Dana Levi", "captured", 80.0, 72, 48, "breach", PID),
                              ("972555000",)], {"name": "dana"}),
    "community_metrics":    ([(10,), (5,), (3,)], {}),
    "follower_growth":      ([[("2026-06-29", 4)]], {}),
    "top_posts":            ([[("DKtq3xZjWm", 10, 2)]], {"limit": 5}),
    "post_engagement":      ([(10,), (2,)], {"shortcode": "DKtq3xZjWm"}),
    "bookings_summary":     ([(7,), (2,), [("Maya", NOW, "confirmed")]], {}),
    "person_360":           ([(PID, "Dana Levi", "BR-1", "lead", "he", NOW),
                              ("captured", NOW),
                              ("long summary", {"k": "v"}, NOW),
                              [("sum", "topic", "anxious", 7, True, NOW)],
                              [("contacted", "whatsapp", NOW)],
                              ("972555000",)], {"name": "dana"}),
    "recent_outbound":      ([[("Dana Levi", "whatsapp", "hi", "erez", NOW)]], {"name": "dana"}),
    "recent_conversations": ([[("Dana Levi", "user", "hello", NOW)]], {"name": "dana"}),
    "content_stats":        ([(10,), (250,), (40,)], {}),
    "growth_trend":         ([[("2026-06-15", 4), ("2026-06-22", 6), ("2026-06-29", 10)]], {}),
    "themes":               ([[("guilt vs. relief", 3), ("rebuild trust", 2)]], {}),
}

# Tables that carry tenant_id — any tool SQL touching them must bind it.
_TENANT_TABLES = ("opportunities", "bookings", "outbound_messages",
                  "person_profile", "session_summaries", "interactions",
                  "FROM person ", "JOIN person ")


def test_every_tool_runs_and_context_block_nonempty():
    for name, (script, args) in HAPPY.items():
        res, _ = run(name, script, args)
        assert res.context_block.strip(), name
        assert res.intent is None or res.intent in ap.FROZEN_INTENTS, name


def test_tenant_id_bound_wherever_schema_allows():
    for name, (script, args) in HAPPY.items():
        _, cur = run(name, script, args)
        for sql, params in cur.data_sql:
            if any(t in sql for t in _TENANT_TABLES):
                assert "tenant_id" in sql, (name, sql)
                assert params and params.get("t") == ap.DEFAULT_TENANT_ID, (name, sql)


def test_every_row_returning_query_is_limited():
    for name, (script, args) in HAPPY.items():
        _, cur = run(name, script, args)
        for sql, _params in cur.data_sql:
            if "COUNT(" in sql and "GROUP BY" not in sql:
                continue                              # scalar aggregate — inherently bounded
            assert "LIMIT" in sql.upper(), (name, sql)


def test_frozen_context_data_shapes():
    """Exact keys GlowingAiAssistant.tsx casts to — the widget contract."""
    expect = {
        "funnel_overview":   ("funnel", {"type", "total_leads", "stages"}),
        "stage_pipeline":    ("pipeline", {"type", "stage", "count", "avg_hours"}),
        "stage_velocity":    ("velocity", {"type", "stage", "avg_hours", "median_hours", "conv_pct"}),
        "sla_overview":      ("sla_overview", {"type", "counts", "top_leads"}),
        "sla_lead_lookup":   ("sla_lead_breach", {"type", "name", "stage", "hours_in_stage",
                                                  "target_hours", "warn_hours", "sla_status",
                                                  "person_id", "wa_phone"}),
        "community_metrics": ("community", {"type", "community_size", "total_likes",
                                            "total_comments", "total_posts"}),
        "follower_growth":   ("growth", {"type", "community_size", "weekly"}),
        "top_posts":         ("top_posts", {"type", "posts"}),
        "post_engagement":   ("post", {"type", "shortcode", "likes", "comments"}),
        "content_stats":     ("content_stats", {"type", "posts", "likes", "comments",
                                                "avg_likes", "avg_comments"}),
        "growth_trend":      ("growth_trend", {"type", "series", "delta_pct"}),
        "themes":            ("themes", {"type", "themes"}),
    }
    for name, (intent, keys) in expect.items():
        script, args = HAPPY[name]
        res, _ = run(name, script, args)
        assert res.intent == intent, name
        assert set(res.ctx_data.keys()) == keys, name

    # Widget item sub-shapes
    res, _ = run("funnel_overview", *HAPPY["funnel_overview"])
    assert len(res.ctx_data["stages"]) == len(ap.PIPELINE_STAGES)
    assert set(res.ctx_data["stages"][0]) == {"stage", "count", "conv_pct"}
    res, _ = run("sla_overview", *HAPPY["sla_overview"])
    assert set(res.ctx_data["top_leads"][0]) == {
        "person_id", "name", "stage", "hours_in_stage",
        "target_hours", "sla_status", "wa_phone"}
    res, _ = run("top_posts", *HAPPY["top_posts"])
    assert set(res.ctx_data["posts"][0]) == {"shortcode", "likes", "comments"}


def test_person_tools_render_as_general_text():
    for name in ("person_360", "recent_outbound", "recent_conversations", "bookings_summary"):
        script, args = HAPPY[name]
        res, _ = run(name, script, args)
        assert res.intent is None and res.ctx_data is None, name
    res, _ = run("person_360", *HAPPY["person_360"])
    assert "Dana Levi" in res.context_block
    assert "SESSION SUMMARIES" in res.context_block
    assert "[sensitive]" in res.context_block         # Option B: operator sees everything


def test_content_stats_math_and_zero_posts_omits_averages():
    res, _ = run("content_stats", [(10,), (250,), (40,)])
    assert res.ctx_data["avg_likes"] == 25.0
    assert res.ctx_data["avg_comments"] == 4.0
    # Zero posts: averages OMITTED (not null) so the widget renders '—'.
    res, _ = run("content_stats", [(0,), (0,), (0,)])
    assert res.intent == "content_stats"
    assert "avg_likes" not in res.ctx_data and "avg_comments" not in res.ctx_data
    assert "averages unavailable" in res.context_block


def test_growth_trend_cumulative_series_and_delta():
    res, _ = run("growth_trend", [[("2026-06-15", 4), ("2026-06-22", 6), ("2026-06-29", 10)]])
    assert res.ctx_data["series"] == [
        {"week": "2026-06-15", "followers": 4},
        {"week": "2026-06-22", "followers": 10},
        {"week": "2026-06-29", "followers": 20},
    ]
    assert res.ctx_data["delta_pct"] == 100.0            # 10 → 20
    # weeks arg trims the window from the LEFT (most recent weeks kept).
    res, _ = run("growth_trend",
                 [[("2026-06-15", 4), ("2026-06-22", 6), ("2026-06-29", 10)]],
                 {"weeks": 2})
    assert [p["week"] for p in res.ctx_data["series"]] == ["2026-06-22", "2026-06-29"]
    # A single week can't produce a delta.
    res, _ = run("growth_trend", [[("2026-06-29", 10)]])
    assert res.ctx_data["delta_pct"] is None


def test_themes_shape_sensitivity_guard_and_empty_case():
    res, cur = run("themes", [[("guilt vs. relief", 3), ("rebuild trust", 2)]])
    assert res.intent == "themes"
    assert res.ctx_data["themes"] == [
        {"theme": "guilt vs. relief", "count": 3},
        {"theme": "rebuild trust", "count": 2},
    ]
    sql, params = cur.data_sql[0]
    assert "sensitive = FALSE" in sql                    # M4: crisis topics never surface
    assert params["n"] == 6                              # default limit
    # Nothing formed yet → honest text block, NO intent claimed (no empty widget).
    res, _ = run("themes", [[]])
    assert res.intent is None and res.ctx_data is None
    assert "no Person-360" in res.context_block


def test_resolve_contract_first_intent_wins_else_general():
    r1 = ap.ToolResult("bookings_summary", "BOOKINGS: …")
    r2 = ap.ToolResult("funnel_overview", "FUNNEL…", "funnel", {"type": "funnel"})
    assert ap.resolve_contract([r1, r2]) == ("funnel", {"type": "funnel"})
    assert ap.resolve_contract([r1]) == ("general", None)
    assert ap.resolve_contract([]) == ("general", None)
    # An out-of-enum intent can never leak into the frozen contract
    rogue = ap.ToolResult("x", "…", "made_up_intent", {"boom": 1})
    assert ap.resolve_contract([rogue]) == ("general", None)


def test_reply_prompt_grounded_or_silent():
    with_data = ap.build_reply_prompt("how's the funnel?", [], [], ["PIPELINE FUNNEL (12 total leads): …"])
    assert "LIVE DATA pulled for this query" in with_data and "12 total leads" in with_data
    without = ap.build_reply_prompt("how's the funnel?", [], [], [])
    assert "LIVE DATA pulled for this query" not in without
    assert "NEVER invent" in without
    with_chips = ap.build_reply_prompt("analyse", ["SLA status overview"], [], ["SLA OVERVIEW: …"])
    assert "SLA status overview" in with_chips


# ── 4. Endpoint regressions — the context-tunnel-vision bug, dead ─────────────

PLAN_FUNNEL = '{"plan": [{"tool": "funnel_overview", "args": {}}]}'
PLAN_COMMUNITY = '{"plan": [{"tool": "community_metrics", "args": {}}]}'
FUNNEL_SCRIPT = [[FM_ROW], [("engaged", 3), ("qualified", 2)], (12,)]


def _post_chat(client, cur, llm_side_effect, message, chips=(), config=None):
    cfg = {"analytics.community_size": "2500"}
    cfg.update(config or {})
    with patch.object(main, "get_db_conn", conn_ctx(cur)), \
         patch.object(main, "_get_config", side_effect=lambda k: cfg.get(k, "")), \
         patch.object(main, "_call_llm", side_effect=llm_side_effect) as llm:
        r = client.post("/api/cockpit/ai/chat",
                        json={"message": message, "chips": list(chips), "history": []})
    return r, llm


def test_regression_plain_text_pipeline_overview_resolves_to_funnel(client):
    """THE bug: plain text + empty chips used to fetch nothing and hallucinate."""
    cur = FakeCursor(FUNNEL_SCRIPT)
    r, llm = _post_chat(client, cur, [PLAN_FUNNEL, "Here is your funnel."],
                        "Show pipeline overview", chips=[])
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"status", "reply", "intent", "context_data", "actions"}
    assert data["status"] == "success"
    assert data["intent"] == "funnel"
    assert data["context_data"]["type"] == "funnel"
    assert data["context_data"]["total_leads"] == 12
    assert data["actions"] == main._AI_ACTIONS["funnel"]
    # Planning call saw the catalog; reply call was grounded in fetched rows.
    assert "AVAILABLE TOOLS" in llm.call_args_list[0].args[0]
    assert "PIPELINE FUNNEL (12 total leads)" in llm.call_args_list[1].args[0]


def test_regression_community_metrics_hits_community_tool(client):
    cur = FakeCursor([(10,), (5,), (3,)])
    r, _ = _post_chat(client, cur, [PLAN_COMMUNITY, "Community is growing."],
                      "Community metrics", chips=[])
    data = r.json()
    assert data["status"] == "success"
    assert data["intent"] == "community"
    assert data["context_data"] == {
        "type": "community", "community_size": 2500,
        "total_likes": 10, "total_comments": 5, "total_posts": 3,
    }
    assert data["actions"] == main._AI_ACTIONS["community"]


def test_planner_garbage_falls_back_to_legacy_router(client):
    """Never dark: unparseable plan → legacy _ACTION_CHIP_MAP path still answers."""
    cur = FakeCursor(FUNNEL_SCRIPT)
    r, llm = _post_chat(client, cur, ["I would suggest looking at the funnel!", "reply"],
                        "Show pipeline overview", chips=[])
    data = r.json()
    assert data["status"] == "success"
    assert data["intent"] == "funnel"                  # legacy router resolved it
    assert data["context_data"]["type"] == "funnel"
    assert llm.call_count == 2                          # failed plan + reply


def test_kill_switch_forces_legacy_router(client):
    cur = FakeCursor(FUNNEL_SCRIPT)
    r, llm = _post_chat(client, cur, ["legacy grounded reply"],
                        "Show pipeline overview", chips=[],
                        config={"ai_chat.planner_enabled": "false"})
    data = r.json()
    assert data["status"] == "success"
    assert data["intent"] == "funnel"
    assert llm.call_count == 1                          # no planning call at all
    assert "AVAILABLE TOOLS" not in llm.call_args_list[0].args[0]


def test_empty_plan_answers_honestly_without_data(client):
    cur = FakeCursor([])
    r, llm = _post_chat(client, cur, ['{"plan": []}', "I don't have data on that."],
                        "thanks!", chips=[])
    data = r.json()
    assert data["status"] == "success"
    assert data["intent"] == "general"
    assert data["context_data"] is None
    assert "LIVE DATA pulled for this query" not in llm.call_args_list[1].args[0]  # grounded-or-silent
    assert cur.data_sql == []                                  # zero queries ran


def test_read_only_guard_wraps_plan_execution(client):
    cur = FakeCursor(FUNNEL_SCRIPT)
    _post_chat(client, cur, [PLAN_FUNNEL, "reply"], "Show pipeline overview")
    control = [sql.strip() for sql, _ in cur.executed
               if sql.strip().upper().startswith(_CONTROL_PREFIXES)]
    assert "SET LOCAL transaction_read_only = on" in control
    assert any(c.startswith("SAVEPOINT") for c in control)
    assert any(c.startswith("ROLLBACK TO SAVEPOINT") for c in control)


def test_empty_input_error_still_carries_full_contract(client):
    """Every return path — including the empty-input refusal — is five-key."""
    r = client.post("/api/cockpit/ai/chat",
                    json={"message": "", "chips": [], "history": []})
    data = r.json()
    assert set(data) == {"status", "reply", "intent", "context_data", "actions"}
    assert data["status"] == "error"
    assert data["intent"] == "general"
    assert data["actions"] == main._AI_ACTIONS["general"]


def test_planner_timeout_falls_back_and_endpoint_still_replies(client):
    cur = FakeCursor(FUNNEL_SCRIPT)
    r, _ = _post_chat(client, cur,
                      [TimeoutError("planner slow"), "legacy reply"],
                      "Show pipeline overview", chips=[])
    data = r.json()
    assert data["status"] == "success"
    assert data["intent"] == "funnel"


# ── 5. Live smoke — opt-in model certification (any provider) ─────────────────

LIVE = os.environ.get("NEXUS_LIVE_LLM_EVALS") == "1"
SMOKE = [
    ("Show pipeline overview", {"funnel_overview"}),
    ("Community metrics", {"community_metrics"}),
    ("מה המצב עם הלידים שחורגים מה-SLA?", {"sla_overview", "sla_lead_lookup"}),
]


@pytest.mark.skipif(not LIVE, reason="set NEXUS_LIVE_LLM_EVALS=1 to run against the real LLM")
@pytest.mark.parametrize("message,accept", SMOKE)
def test_live_planner_smoke(message, accept):
    raw = main._call_llm(ap.build_planner_prompt(message, [], []))
    steps = ap.parse_plan(main._parse_llm_json(raw))
    assert steps, f"live model returned empty plan for {message!r}: {raw!r}"
    assert {s.tool for s in steps} & accept, f"{message!r} → {[s.tool for s in steps]}"
