"""
Unit tests for the pure Work Queue ranking (no DB): nexus.work_queue.recommend
turns one opportunity's signals into the Action / Confidence / Reason trio plus
a ranking priority, and the small helpers (initials, label_for_kind).
"""

import pytest

from nexus.work_queue import (
    Recommendation,
    Signals,
    initials,
    label_for_kind,
    recommend,
)


def _rec(stage, **kw):
    return recommend(Signals(stage=stage, **kw))


class TestRecommendedAction:
    @pytest.mark.parametrize("stage,expected_action", [
        ("captured", "Send the booking link"),
        ("briefed", "Offer two consultation times"),
        ("booked", "Confirm the upcoming session"),
    ])
    def test_stage_drives_action(self, stage, expected_action):
        assert _rec(stage).action == expected_action

    def test_qualified_active_vs_quiet(self):
        active = _rec("qualified", hours_since_last=2)
        quiet = _rec("qualified", hours_since_last=72)
        assert active.action == "Ask the qualifying follow-up"
        assert quiet.action == "Re-engage with a check-in"
        assert "72" not in quiet.reason  # reason renders age in days, not raw hours
        assert "3d" in quiet.reason

    def test_engaged_click_beats_quiet_beats_fresh(self):
        clicked = _rec("engaged", hours_since_last=50, recent_kinds=frozenset({"outreach_click"}))
        quiet = _rec("engaged", hours_since_last=50)
        fresh = _rec("engaged", hours_since_last=1)
        assert clicked.action == "Follow up on the link click"
        assert quiet.action == "Reopen with a gentle nudge"
        assert fresh.action == "Open the conversation"

    def test_unknown_stage_fails_to_opening(self):
        assert _rec("weird-stage").action == "Open the conversation"

    def test_returns_recommendation_with_bounded_confidence(self):
        r = _rec("captured")
        assert isinstance(r, Recommendation)
        assert 0 <= r.confidence <= 100


class TestPriorityRanking:
    def test_hotter_stage_outranks_colder(self):
        assert _rec("captured").priority > _rec("engaged").priority

    def test_urgency_raises_priority(self):
        assert _rec("qualified", urgency=9).priority > _rec("qualified").priority

    def test_urgency_bump_is_capped(self):
        # urgency 10 and 20 both cap at +30, so they tie on the urgency term
        assert _rec("engaged", urgency=10).priority == _rec("engaged", urgency=99).priority

    def test_cooling_midfunnel_lead_gets_pressure(self):
        cooling = _rec("captured", hours_since_last=48)   # 24..120h window
        fresh = _rec("captured", hours_since_last=2)
        assert cooling.priority > fresh.priority

    def test_recent_click_raises_priority(self):
        assert (
            _rec("engaged", recent_kinds=frozenset({"outreach_click"})).priority
            > _rec("engaged").priority
        )


class TestHelpers:
    @pytest.mark.parametrize("name,expected", [
        ("Maya Goren", "MG"),
        ("Daniel", "DA"),
        ("", "—"),
        (None, "—"),
        ("noa levi cohen", "NL"),
    ])
    def test_initials(self, name, expected):
        assert initials(name) == expected

    def test_label_for_kind_known_and_fallback(self):
        assert label_for_kind("outreach_click") == "Clicked the outreach link"
        assert label_for_kind("some_new_kind") == "Some new kind"
