"""
nexus.dossier — the proactive-UX brain: the Morning Briefing diff and the
Person Dossier narrative (summary chapters + relationship trajectory).

Powers the cockpit's proactive layer (Phase 3):
  • GET /api/cockpit/briefing            → build_briefing_items(...)
  • GET /api/cockpit/person/{id}/dossier → build_chapters(...) + build_trajectory(...)

Pure and side-effect-free like nexus.work_queue: the endpoints gather rows,
this module decides. No DB, no I/O, no LLM — the "AI-summarized chapters" are
assembled deterministically from session_summaries, which the daily formation
cron already writes with an LLM (nexus.memory). That keeps the dossier cheap
(zero tokens per view), honest (only formed memory is shown), and the whole
narrative unit-testable (tests/test_nexus_dossier.py).

Trajectory semantics: session urgency (1 = calm/curious … 5 = acute distress)
is the only longitudinal affect signal the spine records, so the trajectory
maps it to [-1, +1] with calm positive:  value = (3 - urgency) / 2.
A rising line means the person is settling; a falling line means strain.
"""
from __future__ import annotations

import datetime

# A return counts as a "reopen" once the silence before it is at least this long.
REOPEN_GAP_DAYS = 7
# A gap between conversations that earns its own "went quiet" chapter.
QUIET_GAP_DAYS = 14

# Caps — one briefing glance, not a feed.
MAX_REOPENED_ITEMS = 2
MAX_NAMES_IN_DETAIL = 4
_CHAPTER_SUMMARY_CAP = 600


def _fmt_day(dt: datetime.datetime | datetime.date | None) -> str:
    """'Jun 8' — locale-free, no platform-specific strftime flags."""
    if dt is None:
        return "?"
    return f"{dt:%b} {dt.day}"


def _fmt_gap(days: float) -> str:
    """Human silence length: '3 weeks' / '10 days'."""
    if days >= 14:
        weeks = round(days / 7)
        return f"{weeks} weeks"
    d = max(1, round(days))
    return f"{d} day" + ("s" if d != 1 else "")


def _names_line(names: list[str]) -> str:
    shown = [n for n in names[:MAX_NAMES_IN_DETAIL] if n]
    extra = len(names) - len(shown)
    line = ", ".join(shown)
    if extra > 0:
        line += f" and {extra} more"
    return line


# ── Morning briefing — the overnight diff ──────────────────────────────────────

def build_briefing_items(*, reopened: list[dict], new_leads: list[str],
                         warn_names: list[str], breach_names: list[str]) -> list[dict]:
    """
    Assemble the briefing items (deterministic; empty list = quiet night).

      reopened     — [{person_id, name, gap_days}] returns after ≥REOPEN_GAP_DAYS
      new_leads    — names of people whose opportunity opened in the window
      warn_names   — leads currently at SLA 'warn' (breach approaching)
      breach_names — leads currently past their SLA target

    Item shape is the MorningBriefing.tsx contract:
      { id, tone: signal|warn|danger, headline, detail, href, cta }
    Ordered story-first: returns, then new arrivals, then accountability.
    """
    items: list[dict] = []

    for r in reopened[:MAX_REOPENED_ITEMS]:
        items.append({
            "id": f"reopen-{r['person_id']}",
            "tone": "signal",
            "headline": f"{r['name']} reopened after {_fmt_gap(r['gap_days'])} of silence",
            "detail": "Came back unprompted — the dossier has the full arc.",
            "href": f"/app/person/{r['person_id']}",
            "cta": "Open dossier",
        })

    if new_leads:
        n = len(new_leads)
        items.append({
            "id": "new-leads",
            "tone": "signal",
            "headline": f"{n} new {'leads' if n != 1 else 'lead'} arrived in the last 24 hours",
            "detail": _names_line(new_leads) + " — untouched until you open.",
            "href": "/app/queue",
            "cta": "Open the queue",
        })

    if warn_names:
        n = len(warn_names)
        items.append({
            "id": "sla-warn",
            "tone": "warn",
            "headline": f"{n} SLA {'breaches' if n != 1 else 'breach'} approaching",
            "detail": _names_line(warn_names) + " — inside the warning window now.",
            "href": "/app/queue",
            "cta": "Open the queue",
        })

    if breach_names:
        n = len(breach_names)
        items.append({
            "id": "sla-breach",
            "tone": "danger",
            "headline": f"{n} {'leads' if n != 1 else 'lead'} past their SLA target",
            "detail": _names_line(breach_names) + " — the clock is already red.",
            "href": "/app/queue",
            "cta": "Open the queue",
        })

    return items


# ── Person dossier — trajectory + chapters ─────────────────────────────────────
# Both take the same input: session-summary rows as dicts, ASCENDING by time:
#   {summary, topic, emotional_state, urgency, sensitive, created_at}

def build_trajectory(summaries: list[dict]) -> list[dict]:
    """Urgency → [-1, +1] relationship-trajectory points (calm positive).
    Rows without urgency (incl. sensitive placeholders) carry no affect signal
    and are skipped. Empty list → the frontend hides the trajectory panel."""
    points = []
    for s in summaries:
        u = s.get("urgency")
        if u is None:
            continue
        u = max(1, min(int(u), 5))
        points.append({
            "label": _fmt_day(s.get("created_at")),
            "value": round((3 - u) / 2.0, 2),
            "at": s["created_at"].isoformat() if s.get("created_at") else None,
        })
    return points


def _week_start(dt: datetime.datetime) -> datetime.date:
    d = dt.date() if isinstance(dt, datetime.datetime) else dt
    return d - datetime.timedelta(days=d.weekday())


def build_chapters(summaries: list[dict]) -> list[dict]:
    """
    The story so far: one chapter per ACTIVE week (formed session summaries,
    grouped by ISO week), with synthetic "Went quiet" chapters inserted for
    silences ≥ QUIET_GAP_DAYS between them. Sensitive sessions surface only
    their stored neutral placeholder (M4: content was never persisted).

    Chapter shape is the PersonDossierPage.tsx contract:
      { id, range, title, summary, signals: [str], at: iso|None }
    """
    dated = [s for s in summaries if s.get("created_at")]
    if not dated:
        return []

    # Group by week, preserving chronological order.
    weeks: list[tuple[datetime.date, list[dict]]] = []
    for s in dated:
        wk = _week_start(s["created_at"])
        if weeks and weeks[-1][0] == wk:
            weeks[-1][1].append(s)
        else:
            weeks.append((wk, [s]))

    chapters: list[dict] = []
    prev_last: datetime.datetime | None = None
    for wk, group in weeks:
        first_at = group[0]["created_at"]

        # A long silence between active weeks is part of the story — name it.
        if prev_last is not None:
            gap_days = (first_at - prev_last).total_seconds() / 86400.0
            if gap_days >= QUIET_GAP_DAYS:
                chapters.append({
                    "id": f"quiet-{len(chapters)}",
                    "range": f"{_fmt_day(prev_last)} – {_fmt_day(first_at)}",
                    "title": "Went quiet",
                    "summary": f"No conversations for {_fmt_gap(gap_days)}.",
                    "signals": [f"{_fmt_gap(gap_days)} of silence"],
                    "at": prev_last.isoformat(),
                })
        prev_last = group[-1]["created_at"]

        title = next((s["topic"] for s in group if s.get("topic")), None)
        if title is None:
            title = "Sensitive session" if all(s.get("sensitive") for s in group) else "Conversation"

        text = " · ".join(str(s.get("summary") or "").strip()
                          for s in group if s.get("summary"))
        n = len(group)
        signals = [f"{n} conversation" + ("s" if n != 1 else "")]
        top_urgency = max((s.get("urgency") or 0) for s in group)
        if top_urgency:
            signals.append(f"urgency {top_urgency}/5")

        chapters.append({
            "id": f"week-{wk.isoformat()}",
            "range": f"Week of {_fmt_day(wk)}",
            "title": title,
            "summary": text[:_CHAPTER_SUMMARY_CAP],
            "signals": signals,
            "at": first_at.isoformat(),
        })

    return chapters
