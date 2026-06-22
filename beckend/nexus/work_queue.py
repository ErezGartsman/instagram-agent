"""
nexus.work_queue — the Decision Engine ranking behind the cockpit Work Queue.

Pure, side-effect-free scoring over the signals we already capture: the open
opportunity's stage, interaction recency + recent kinds, and the latest session
urgency. Given one opportunity's `Signals` it returns the single recommended
next move, a 0–100 confidence, and a human reason — the Action / Confidence /
Reason trust trio — plus an integer `priority` used to rank the queue
(higher = surface sooner).

No DB and no I/O here: the endpoint gathers rows, this module decides. That
keeps the brain unit-testable in isolation (tests/test_nexus_work_queue.py) and
the tuning (weights, thresholds) all in one readable place.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Human labels for the Person-360 activity timeline (signal log → readable).
KIND_LABELS = {
    "session_started":  "Started a conversation",
    "icebreaker_hit":   "Opened with the icebreaker",
    "trigger_hit":      "Hit an interest trigger",
    "qualified":        "Qualified",
    "captured":         "Shared their context",
    "context_provided": "Provided more context",
    "stage_change":     "Moved stage",
    "booking_created":  "Booked a consultation",
    "booking_canceled": "Canceled the booking",
    "outreach_click":   "Clicked the outreach link",
    "contacted":        "Was contacted",
    "note_added":       "Note added",
    "alert_sent":       "Alert sent",
    "crm_synced":       "Synced to CRM",
    "handled":          "Handled in the queue",
    "snoozed":          "Snoozed for later",
}

# Base priority by stage — closer to a booking is hotter, with captured/briefed
# the hottest (a warm lead about to convert). 'booked' is already won, so it sits
# low: it still earns a confirm action but should not crowd out live work.
_STAGE_WEIGHT = {
    "engaged": 20, "qualified": 45, "captured": 70, "briefed": 75, "booked": 30,
}

# Mid-funnel stages where going quiet is a risk worth surfacing.
_COOLING_STAGES = {"qualified", "captured", "briefed"}

# A lead is "quiet" once this many hours pass with no interaction.
_QUIET_HOURS = 36


def label_for_kind(kind: str) -> str:
    """Readable timeline label for an interaction kind (fallback: prettified)."""
    return KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())


def initials(name: str | None) -> str:
    """Up-to-two-letter avatar initials from a display name."""
    parts = [w for w in (name or "").split() if w]
    if not parts:
        return "—"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _age(hours: float | None) -> str:
    if hours is None:
        return ""
    if hours < 1:
        return "moments ago"
    if hours < 24:
        return f"{round(hours)}h"
    return f"{round(hours / 24)}d"


@dataclass
class Signals:
    """Everything the ranking needs about one open opportunity."""
    stage: str
    hours_since_last: float | None = None          # None = no interactions yet
    recent_kinds: frozenset[str] = field(default_factory=frozenset)
    urgency: int | None = None                     # latest session urgency, 1..10


@dataclass
class Recommendation:
    action: str
    confidence: int
    reason: str
    priority: int


def recommend(s: Signals) -> Recommendation:
    """The brain: signals → (action, confidence, reason, priority)."""
    stage = s.stage
    h = s.hours_since_last
    quiet = h is not None and h >= _QUIET_HOURS
    clicked = "outreach_click" in s.recent_kinds

    # ── the next move (Action) + how sure we are (Confidence) + why (Reason) ──
    if stage == "booked":
        action, conf, why = "Confirm the upcoming session", 80, "booked — confirm and prep"
    elif stage == "briefed":
        action, conf, why = "Offer two consultation times", 84, "fully briefed; ready to schedule"
    elif stage == "captured":
        action, conf, why = "Send the booking link", 88, "shared their context — ready to book"
    elif stage == "qualified":
        if quiet:
            action, conf, why = "Re-engage with a check-in", 66, f"qualified, then quiet {_age(h)}"
        else:
            action, conf, why = "Ask the qualifying follow-up", 74, "qualified and active"
    else:  # 'engaged' or anything unknown — fail toward gently opening contact
        if clicked:
            action, conf, why = "Follow up on the link click", 72, "clicked through, no reply yet"
        elif quiet:
            action, conf, why = "Reopen with a gentle nudge", 52, f"went quiet {_age(h)} after first contact"
        else:
            action, conf, why = "Open the conversation", 60, "newly engaged"

    # ── priority (ranking) — stage weight, urgency, cooling pressure, click ──
    priority = _STAGE_WEIGHT.get(stage, 15)
    if s.urgency:
        priority += min(30, s.urgency * 3)
    # a hot mid-funnel lead cooling off is the most time-sensitive thing here
    if stage in _COOLING_STAGES and h is not None and 24 <= h <= 120:
        priority += 15
    if clicked:
        priority += 10

    return Recommendation(action=action, confidence=conf, reason=why, priority=priority)
