"""
tests.test_nexus_flows_policy — the Policy Gate. Pattern B (FakeConn) for
DB-touching functions; pure asserts for quiet_hours_block/pressure_budget.

configure() installs module-level globals — every test resets them via
monkeypatch (auto-reverted) so no test can leak its fakes into another.
"""
import datetime

import pytest

from nexus.flows import policy
from tests._flows_fakes import FakeConn


# ── Pure sub-checks ─────────────────────────────────────────────────────────────

class TestQuietHoursBlock:
    @pytest.mark.parametrize("hour,expected", [
        (21, True), (23, True), (0, True), (8, True),   # inside the window
        (9, False), (12, False), (20, False),            # outside the window
    ])
    def test_boundaries(self, hour, expected):
        moment = datetime.datetime(2026, 7, 10, hour, 0, tzinfo=policy._IL_TZ)
        assert policy.quiet_hours_block(moment) is expected

    def test_utc_input_is_converted_to_israel_time(self):
        # 20:00 UTC in July is 23:00 Israel (DST, UTC+3) — inside the window.
        moment = datetime.datetime(2026, 7, 10, 20, 0, tzinfo=datetime.timezone.utc)
        assert policy.quiet_hours_block(moment) is True

    def test_naive_datetime_is_treated_as_utc(self):
        moment = datetime.datetime(2026, 7, 10, 20, 0)   # no tzinfo
        assert policy.quiet_hours_block(moment) is True


class TestConfigHelpers:
    def test_pressure_budget_default_when_unconfigured(self):
        policy.configure(is_crisis_fn=None, channel_eligibility_fn=None,
                         get_config_fn=None, notify_operator_fn=None)
        assert policy.pressure_budget() == policy._DEFAULT_PRESSURE_BUDGET

    def test_pressure_budget_reads_config(self, monkeypatch):
        policy.configure(is_crisis_fn=None, channel_eligibility_fn=None,
                         get_config_fn=lambda k: "5", notify_operator_fn=None)
        assert policy.pressure_budget() == 5

    def test_pressure_budget_falls_back_on_malformed_value(self):
        policy.configure(is_crisis_fn=None, channel_eligibility_fn=None,
                         get_config_fn=lambda k: "not-a-number", notify_operator_fn=None)
        assert policy.pressure_budget() == policy._DEFAULT_PRESSURE_BUDGET

    def test_flows_enabled_default_off(self):
        policy.configure(is_crisis_fn=None, channel_eligibility_fn=None,
                         get_config_fn=lambda k: "", notify_operator_fn=None)
        assert policy.flows_enabled() is False

    def test_flows_enabled_true(self):
        policy.configure(is_crisis_fn=None, channel_eligibility_fn=None,
                         get_config_fn=lambda k: "true" if k == "flows.enabled" else "",
                         notify_operator_fn=None)
        assert policy.flows_enabled() is True


# ── DB-touching helpers ──────────────────────────────────────────────────────────

class TestCountRecentAutomatedSends:
    def test_returns_count(self):
        conn = FakeConn(fetchone_queue=[(3,)])
        assert policy.count_recent_automated_sends(conn, "p1") == 3

    def test_zero_when_none_returned(self):
        conn = FakeConn(fetchone_queue=[(None,)])
        assert policy.count_recent_automated_sends(conn, "p1") == 0

    def test_query_filters_automated_prefixes_only(self):
        conn = FakeConn(fetchone_queue=[(0,)])
        policy.count_recent_automated_sends(conn, "p1")
        stmt, params = conn.executed[0]
        assert "outbound_messages" in stmt
        assert "sent_by LIKE" in stmt
        assert "agent:%" in params and "flow:%" in params and "cron:%" in params


class TestFetchRecentInboundText:
    def test_returns_body(self):
        conn = FakeConn(fetchone_queue=[("help me",)])
        assert policy.fetch_recent_inbound_text(conn, "p1", "whatsapp") == "help me"

    def test_none_when_no_row(self):
        conn = FakeConn(fetchone_queue=[None])
        assert policy.fetch_recent_inbound_text(conn, "p1", "whatsapp") is None

    def test_never_raises_on_db_error(self):
        conn = FakeConn(fail_prefix="SELECT m.body")
        assert policy.fetch_recent_inbound_text(conn, "p1", "whatsapp") is None


# ── evaluate_send — the veto ordering ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_policy_bridge():
    """Every evaluate_send test configures its own fakes; this just ensures
    a clean slate (a previous test's configure() can't leak in)."""
    yield
    policy.configure(is_crisis_fn=None, channel_eligibility_fn=None,
                     get_config_fn=None, notify_operator_fn=None)


class TestEvaluateSendOrdering:
    def _configure(self, *, crisis=False, budget="2", eligible=True, eligible_reason=None):
        policy.configure(
            is_crisis_fn=lambda text: crisis,
            channel_eligibility_fn=lambda conn, pid, ch: {"eligible": eligible, "reason": eligible_reason},
            get_config_fn=lambda k: budget if k == "flows.pressure_budget" else "",
            notify_operator_fn=None,
        )

    def test_crisis_vetoes_first(self):
        self._configure(crisis=True)
        conn = FakeConn(fetchone_queue=[("i want to end it all",)])   # crisis text lookup
        verdict = policy.evaluate_send(conn, person_id="p1")
        assert verdict.allowed is False
        assert verdict.reason == "crisis"

    def test_no_recent_inbound_means_no_crisis_veto(self):
        self._configure(crisis=True)   # is_crisis_fn would say yes if asked
        conn = FakeConn(fetchone_queue=[
            None,      # fetch_recent_inbound_text -> nothing recent -> crisis check skipped
            (0,),      # count_recent_automated_sends
        ])
        verdict = policy.evaluate_send(conn, person_id="p1",
                                       now=datetime.datetime(2026, 7, 10, 12, tzinfo=policy._IL_TZ))
        assert verdict.allowed is True

    def test_pressure_budget_vetoes_second(self):
        self._configure(crisis=False, budget="2")
        conn = FakeConn(fetchone_queue=[
            None,      # fetch_recent_inbound_text
            (2,),      # count_recent_automated_sends — at budget
        ])
        verdict = policy.evaluate_send(conn, person_id="p1")
        assert verdict.allowed is False
        assert verdict.reason == "pressure_budget"

    def test_quiet_hours_vetoes_third(self):
        self._configure(crisis=False, budget="5")
        conn = FakeConn(fetchone_queue=[None, (0,)])
        verdict = policy.evaluate_send(
            conn, person_id="p1",
            now=datetime.datetime(2026, 7, 10, 23, tzinfo=policy._IL_TZ),   # inside quiet window
        )
        assert verdict.allowed is False
        assert verdict.reason == "quiet_hours"

    def test_channel_eligibility_vetoes_fourth(self):
        self._configure(crisis=False, budget="5", eligible=False, eligible_reason="window_expired")
        conn = FakeConn(fetchone_queue=[None, (0,)])
        verdict = policy.evaluate_send(
            conn, person_id="p1",
            now=datetime.datetime(2026, 7, 10, 12, tzinfo=policy._IL_TZ),
        )
        assert verdict.allowed is False
        assert verdict.reason == "window_expired"

    def test_allowed_when_everything_passes(self):
        self._configure(crisis=False, budget="5", eligible=True)
        conn = FakeConn(fetchone_queue=[None, (0,)])
        verdict = policy.evaluate_send(
            conn, person_id="p1",
            now=datetime.datetime(2026, 7, 10, 12, tzinfo=policy._IL_TZ),
        )
        assert verdict.allowed is True
        assert verdict.reason is None


# ── guarded_whatsapp_send — the orchestration ────────────────────────────────────

class TestGuardedWhatsappSend:
    def _configure_permissive(self):
        policy.configure(
            is_crisis_fn=lambda text: False,
            channel_eligibility_fn=lambda conn, pid, ch: {"eligible": True, "reason": None},
            get_config_fn=lambda k: "5" if k == "flows.pressure_budget" else "",
            notify_operator_fn=None,
        )

    def test_source_must_be_automated_prefix(self):
        self._configure_permissive()
        conn = FakeConn()
        with pytest.raises(ValueError, match="must start with one of"):
            policy.guarded_whatsapp_send(conn, person_id="p1", text="hi", source="erez@example.com")

    def test_blocked_by_policy_never_touches_identity_or_whatsapp(self, monkeypatch):
        policy.configure(
            is_crisis_fn=lambda text: True,
            channel_eligibility_fn=lambda conn, pid, ch: {"eligible": True, "reason": None},
            get_config_fn=lambda k: "",
            notify_operator_fn=None,
        )
        called = {"resolve": False, "send": False}
        monkeypatch.setattr(policy.nexus_identity, "resolve_whatsapp_recipient",
                            lambda conn, pid: called.__setitem__("resolve", True) or "9725551234")
        monkeypatch.setattr(policy.nexus_whatsapp, "send_text",
                            lambda r, t: called.__setitem__("send", True) or "{}")
        conn = FakeConn(fetchone_queue=[("i want to end it all",)])
        outcome = policy.guarded_whatsapp_send(conn, person_id="p1", text="hi", source="flow:x")
        assert outcome.sent is False
        assert outcome.verdict.reason == "crisis"
        assert called == {"resolve": False, "send": False}

    def test_no_whatsapp_number_blocks_after_policy_passes(self, monkeypatch):
        self._configure_permissive()
        monkeypatch.setattr(policy.nexus_identity, "resolve_whatsapp_recipient", lambda conn, pid: None)
        conn = FakeConn(fetchone_queue=[None, (0,)])   # crisis lookup, pressure count
        outcome = policy.guarded_whatsapp_send(conn, person_id="p1", text="hi", source="agent:qualification")
        assert outcome.sent is False
        assert outcome.verdict.reason == "no_whatsapp_number"

    def test_send_failure_reported_distinctly(self, monkeypatch):
        self._configure_permissive()
        monkeypatch.setattr(policy.nexus_identity, "resolve_whatsapp_recipient", lambda conn, pid: "9725551234")
        monkeypatch.setattr(policy.nexus_whatsapp, "send_text", lambda r, t: None)
        conn = FakeConn(fetchone_queue=[None, (0,)])
        outcome = policy.guarded_whatsapp_send(conn, person_id="p1", text="hi", source="flow:x")
        assert outcome.sent is False
        assert outcome.verdict.reason == "send_failed"

    def test_happy_path_sends_persists_and_logs(self, monkeypatch):
        self._configure_permissive()
        monkeypatch.setattr(policy.nexus_identity, "resolve_whatsapp_recipient", lambda conn, pid: "9725551234")
        monkeypatch.setattr(policy.nexus_whatsapp, "send_text",
                            lambda r, t: '{"messages":[{"id":"wamid.abc123"}]}')
        conn = FakeConn(
            fetchone_queue=[None, (0,)],   # crisis lookup, pressure count
            rowcount_queue=[1],            # the log_interaction ON CONFLICT insert
        )
        outcome = policy.guarded_whatsapp_send(
            conn, person_id="p1", text="hi there", source="flow:cooling-lead-nudge",
            opportunity_id="opp1",
        )
        assert outcome.sent is True
        assert outcome.provider_message_id == "wamid.abc123"

        insert_stmts = [s for s, _ in conn.executed if "INSERT INTO outbound_messages" in s]
        assert len(insert_stmts) == 1
        contacted_stmts = [
            (s, p) for s, p in conn.executed if "INSERT INTO interactions" in s
        ]
        assert len(contacted_stmts) == 1
        assert contacted_stmts[0][1][0] == "contacted"   # kind
