"""
nexus.memory — light memory formation (Ticket 3.5, Phase 1: shadow mode).

Reads a person's conversations and distils them into durable memory:
  • session_summaries — one episodic row per conversation
  • person_profile    — one evolving semantic row per person

SHADOW MODE: formation runs in the background (the daily cron sweep) and writes
ONLY to the memory tables. It never sends a message and never changes the bot's
conversational voice — recall (injecting memory back into the bot prompt) is a
SEPARATE switch (memory.recall_enabled), still OFF.

Dependency injection: this module never imports main (no circular import). The
LLM call, the JSON repair parser, and the crisis detector are passed in by the
caller (main.py's cron endpoint), so the battle-tested implementations are
reused rather than duplicated.

GOVERNANCE (M4): a session that trips the crisis detector is recorded as a
neutral, content-free summary (sensitive=true) and contributes NOTHING to the
profile. Intimate crisis content is never persisted as memory.

Pure helpers (prompt build, parse, merge) are unit-tested without a DB; the
DB-touching paths are exercised against the live sweep in shadow mode.
"""

import json
import logging
from collections import defaultdict

from nexus import db

logger = logging.getLogger("nexus.memory")

# Neutral placeholder stored instead of any crisis content (M4).
_SENSITIVE_SUMMARY = "שיחה רגישה — לא נשמר תוכן."

# Caps keep one bad LLM response from bloating a row.
_MAX_FACTS = 20
_SUMMARY_CAP = 1500
_FIELD_CAP = 120

FORMATION_PROMPT = """\
You are keeping a private pre-call memory note for Erez Gartsman, a relationships
& dating coach, about ONE person he is in contact with. Read what we already know
and a new conversation, then return an UPDATED understanding — the way a
thoughtful coach jots notes before a call.

=== WHAT WE KNOW SO FAR (may be empty) ===
{existing}

=== NEW CONVERSATION (oldest → newest) ===
{transcript}

Return ONLY a strict JSON object, nothing else:
{{"session_summary": "<1-2 Hebrew sentences: what THIS conversation was about>",
  "topic": "<2-5 Hebrew words>",
  "emotional_state": "<2-4 Hebrew words>",
  "urgency": <integer 1-5>,
  "profile_summary": "<2-4 ENGLISH sentences: who this person is, their situation, and what they seem to need — integrate prior knowledge WITH this conversation>",
  "attributes": {{"relationship_status": "<value or null>", "core_concern": "<value or null>", "goal": "<ENGLISH value or null>", "tension": "<ENGLISH value or null>", "communication_style": "<value or null>"}},
  "facts": ["<short durable Hebrew fact grounded in their words>"]}}

Rules:
- Ground EVERYTHING in their actual words — never invent facts.
- urgency: 1 = casual/curious, 5 = acute distress / wants help now.
- attributes: include a key's value only if the conversation supports it; else null.
- attributes.core_concern: the PROBLEM weighing on them (e.g. "חוסר תקשורת בזוגיות").
- attributes.goal: the ONE outcome they are working toward, in their own framing
  (e.g. "decide whether to stay before the anniversary", "rebuild trust after the affair").
  Capture it whenever the conversation makes it reasonably clear — null only when
  there is genuinely no signal. Do NOT invent a goal they did not express.
- attributes.tension: the emotional tug-of-war underneath the goal, as two poles
  (e.g. "guilt vs. relief", "pride vs. need"). Null when there is no clear signal.
- LANGUAGE — this is a hard rule: output the summaries for Goal, Tension, and
  Essence (the profile_summary) ONLY in English, regardless of the input language.
  These three fields power an English-only operator dashboard. Everything else
  (session_summary, topic, emotional_state, facts) stays in HEBREW.
- facts: 0-4 concrete, durable facts. Nothing the person did not actually say.
- No markdown, no commentary, nothing outside the JSON.
"""


# ─── Pure helpers (no DB) ─────────────────────────────────────────────────────

def render_transcript(messages: list[tuple]) -> str:
    """messages: list of (role, content) oldest→newest → a compact transcript."""
    lines = []
    for role, content in messages:
        who = "משתמש" if role == "user" else "עוזר"
        lines.append(f"{who}: {(content or '').strip()}")
    return "\n".join(lines)


def render_existing(profile: dict | None) -> str:
    """Render the current profile for the prompt, or a placeholder when new."""
    if not profile or not (profile.get("summary") or profile.get("facts")):
        return "(אין מידע קודם — זו ההיכרות הראשונה)"
    parts = []
    if profile.get("summary"):
        parts.append(profile["summary"])
    facts = [f.get("fact") for f in (profile.get("facts") or []) if f.get("fact")]
    if facts:
        parts.append("עובדות ידועות: " + " · ".join(facts[:_MAX_FACTS]))
    return "\n".join(parts)


def _clamp_urgency(value) -> int | None:
    try:
        return max(1, min(int(value), 5))
    except (TypeError, ValueError):
        return None


def parse_formation(parsed: dict) -> dict | None:
    """
    Normalize a parsed formation JSON into the fields we persist. Returns None
    when there is no usable summary (we never write an empty memory row).
    """
    if not isinstance(parsed, dict):
        return None
    session_summary = (parsed.get("session_summary") or "").strip()[:_SUMMARY_CAP]
    profile_summary = (parsed.get("profile_summary") or "").strip()[:_SUMMARY_CAP]
    if not session_summary and not profile_summary:
        return None
    attrs_in = parsed.get("attributes") or {}
    attributes = {
        str(k): str(v).strip()[:_FIELD_CAP]
        for k, v in attrs_in.items()
        if v not in (None, "", "null") and str(v).strip().lower() != "null"
    } if isinstance(attrs_in, dict) else {}
    facts_in = parsed.get("facts") or []
    facts = [str(f).strip()[:_FIELD_CAP] for f in facts_in
             if isinstance(facts_in, list) and str(f).strip()][:4]
    return {
        "session_summary": session_summary or None,
        "topic":           (parsed.get("topic") or "").strip()[:_FIELD_CAP] or None,
        "emotional_state": (parsed.get("emotional_state") or "").strip()[:_FIELD_CAP] or None,
        "urgency":         _clamp_urgency(parsed.get("urgency")),
        "profile_summary": profile_summary or None,
        "attributes":      attributes,
        "facts":           facts,
    }


def merge_profile(existing: dict | None, formation: dict, *, session_id: str) -> dict:
    """
    Merge a new formation into the existing profile. CRITICAL: operator-authored
    facts (by='operator') are NEVER removed or overwritten by AI — the AI only
    ever adds/refreshes its own facts. Attributes: new non-null values win per
    key, prior keys are preserved. Returns the row to upsert.
    """
    existing = existing or {}
    prior_attrs = existing.get("attributes") or {}
    merged_attrs = {**prior_attrs, **formation["attributes"]}

    prior_facts = existing.get("facts") or []
    operator_facts = [f for f in prior_facts if f.get("by") == "operator"]
    ai_facts = [f for f in prior_facts if f.get("by") != "operator"]
    seen = {f.get("fact") for f in ai_facts}
    for fact in formation["facts"]:
        if fact not in seen:
            ai_facts.append({"fact": fact, "by": "ai", "session_id": session_id})
            seen.add(fact)
    # operator facts always kept; AI facts capped to the most recent.
    merged_facts = operator_facts + ai_facts[-_MAX_FACTS:]

    return {
        "summary": formation["profile_summary"] or existing.get("summary"),
        "attributes": merged_attrs,
        "facts": merged_facts,
        "version": int(existing.get("version") or 0) + 1,
    }


# ─── Recall (Hook F — Phase 2): memory → the bot's prompt ─────────────────────

def build_recall_block(conn, *, session_id: str) -> str:
    """
    Build the Hebrew recall block injected into the conversational prompt for a
    KNOWN person: profile summary + durable facts + recent session summaries
    (sensitive ones excluded at the SQL level — M4). Returns "" whenever there
    is nothing to recall or anything fails — the bot must never break or sound
    different because recall hiccuped. Read-only; gated by the caller behind
    memory.recall_enabled.

    The guardrail instructions ride INSIDE the block so every consumer prompt
    (Telegram triage today, the WhatsApp flow in Sprint 4) inherits them:
    reference gently, never assert the uncertain, never mention "memory".
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT person_id FROM sessions WHERE id = %s", (session_id,)
            )
            row = cur.fetchone()
            if not row or not row[0]:
                return ""
            person_id = str(row[0])
            cur.execute(
                "SELECT summary, facts FROM person_profile WHERE person_id = %s",
                (person_id,),
            )
            prof = cur.fetchone()
            cur.execute(
                "SELECT summary FROM session_summaries "
                "WHERE person_id = %s AND sensitive = FALSE "
                "ORDER BY created_at DESC LIMIT 3",
                (person_id,),
            )
            sums = [r[0] for r in cur.fetchall() if r[0]]

        if not prof and not sums:
            return ""
        lines = ["=== רקע פנימי על הפונה (לשימושך בלבד — אל תצטט) ==="]
        if prof and prof[0]:
            lines.append(prof[0])
        if prof and prof[1]:
            facts = [f.get("fact") for f in prof[1]
                     if isinstance(f, dict) and f.get("fact")]
            if facts:
                lines.append("עובדות שכדאי לזכור: " + " · ".join(facts[:6]))
        if sums:
            lines.append("משיחות קודמות: " + " | ".join(sums))
        lines.append(
            "הנחיות זיכרון: התייחס/י לרקע רק אם הוא רלוונטי, בעדינות ובטבעיות — "
            "כמו מכר שזוכר, לא כמו מערכת. לעולם אל תזכיר/י 'זיכרון' או 'מערכת'. "
            "אם פרט אינו ודאי — אל תניח/י אותו ואל תציין/י אותו."
        )
        return "\n".join(lines) + "\n\n"
    except Exception as e:
        logger.warning("[memory] recall block failed (session=%s): %s",
                       session_id, e)
        return ""


# ─── DB-touching (commit-free; caller owns the transaction) ───────────────────

def _load_profile(conn, person_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT summary, attributes, facts, version, updated_by "
            "FROM person_profile WHERE person_id = %s",
            (person_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"summary": row[0], "attributes": row[1], "facts": row[2],
            "version": row[3], "updated_by": row[4]}


def _write_session_summary(conn, *, session_id, person_id, summary, topic,
                           emotional_state, urgency, sensitive, model_version):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO session_summaries "
            "(session_id, person_id, summary, topic, emotional_state, urgency, "
            " sensitive, model_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (session_id) DO NOTHING",
            (session_id, person_id, summary, topic, emotional_state, urgency,
             sensitive, model_version),
        )


def _upsert_profile(conn, person_id, merged, model_version):
    # updated_by guard: never overwrite a profile a human last touched.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO person_profile "
            "(person_id, summary, attributes, facts, version, model_version, updated_by) "
            "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, 'ai') "
            "ON CONFLICT (person_id) DO UPDATE SET "
            "  summary = EXCLUDED.summary, attributes = EXCLUDED.attributes, "
            "  facts = EXCLUDED.facts, version = EXCLUDED.version, "
            "  model_version = EXCLUDED.model_version, updated_at = NOW() "
            "WHERE person_profile.updated_by <> 'operator'",
            (person_id, merged["summary"],
             json.dumps(merged["attributes"], ensure_ascii=False),
             json.dumps(merged["facts"], ensure_ascii=False),
             merged["version"], model_version),
        )


def run_session_formation(conn, *, session_id, person_id, channel,
                          call_llm, parse_json, is_crisis_fn,
                          model_version) -> str:
    """
    Form memory for ONE session. Commit-free — the sweep commits per session.
    Returns: 'sensitive' | 'formed' | 'failed' | 'empty'.
    """
    from nexus import interactions

    with conn.cursor() as cur:
        cur.execute(
            "SELECT role, content FROM messages "
            "WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        )
        messages = [(r[0], r[1]) for r in cur.fetchall()]
    if not messages:
        return "empty"

    user_text = " ".join(c for r, c in messages if r == "user")

    # M4: crisis sessions store a neutral, content-free summary and NO profile.
    if is_crisis_fn(user_text):
        _write_session_summary(
            conn, session_id=session_id, person_id=person_id,
            summary=_SENSITIVE_SUMMARY, topic=None, emotional_state=None,
            urgency=None, sensitive=True, model_version=model_version)
        interactions.log_interaction(
            conn, "formation_run", channel, person_id=person_id,
            session_id=session_id, payload={"sensitive": True},
            dedup_key=f"formation:{session_id}")
        return "sensitive"

    existing = _load_profile(conn, person_id)
    prompt = FORMATION_PROMPT.format(
        existing=render_existing(existing),
        transcript=render_transcript(messages)[:6000],
    )
    try:
        formation = parse_formation(parse_json(call_llm(prompt)))
    except Exception as e:
        logger.warning("[memory] formation LLM/parse failed (session=%s): %s",
                       session_id, e)
        return "failed"
    if not formation:
        return "failed"

    _write_session_summary(
        conn, session_id=session_id, person_id=person_id,
        summary=formation["session_summary"] or "—", topic=formation["topic"],
        emotional_state=formation["emotional_state"], urgency=formation["urgency"],
        sensitive=False, model_version=model_version)

    merged = merge_profile(existing, formation, session_id=session_id)
    _upsert_profile(conn, person_id, merged, model_version)

    interactions.log_interaction(
        conn, "formation_run", channel, person_id=person_id,
        session_id=session_id, payload={"urgency": formation["urgency"]},
        dedup_key=f"formation:{session_id}")
    return "formed"


def select_eligible_sessions(conn, *, batch_size: int, idle_minutes: int) -> list:
    """
    Sessions ready for formation: stamped with a person, idle long enough to be
    'done', not yet summarised, and carrying a real conversation (≥2 user
    messages). Newest-idle first. Re-running is safe — summarised sessions drop
    out via the NOT EXISTS guard.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.id, s.person_id, s.channel "
            "FROM sessions s "
            "WHERE s.person_id IS NOT NULL "
            "  AND s.last_active < NOW() - make_interval(mins => %s) "
            "  AND NOT EXISTS (SELECT 1 FROM session_summaries ss "
            "                  WHERE ss.session_id = s.id) "
            "  AND (SELECT COUNT(*) FROM messages m "
            "       WHERE m.session_id = s.id AND m.role = 'user') >= 2 "
            "ORDER BY s.last_active DESC "
            "LIMIT %s",
            (idle_minutes, batch_size),
        )
        return [(str(r[0]), str(r[1]), r[2]) for r in cur.fetchall()]


def formation_sweep(*, call_llm, parse_json, is_crisis_fn, model_version,
                    batch_size: int = 8, idle_minutes: int = 30) -> dict:
    """
    One shadow-mode sweep. Each session is formed and committed independently,
    so one failure never loses the batch and the function stays well within the
    serverless time budget (batch_size small, one LLM call each). Returns
    per-outcome counts.
    """
    stats: dict = defaultdict(int)
    with db.get_conn() as conn:
        eligible = select_eligible_sessions(
            conn, batch_size=batch_size, idle_minutes=idle_minutes)
    for session_id, person_id, channel in eligible:
        try:
            with db.get_conn() as conn:
                outcome = run_session_formation(
                    conn, session_id=session_id, person_id=person_id,
                    channel=channel, call_llm=call_llm, parse_json=parse_json,
                    is_crisis_fn=is_crisis_fn, model_version=model_version)
                conn.commit()
            stats[outcome] += 1
        except Exception as e:
            logger.warning("[memory] formation failed (session=%s): %s",
                           session_id, e)
            stats["error"] += 1
    stats["eligible"] = len(eligible)
    return dict(stats)
