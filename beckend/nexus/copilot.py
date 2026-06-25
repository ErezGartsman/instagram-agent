"""
nexus.copilot — P2 "The Ambient Copilot" — pure context + prompt helpers.

This module has NO LLM client. It assembles the context envelope, builds the
draft prompt, and owns the Copilot persona. The actual LLM call (Gemini, via
main.py's _call_llm) and the SSE word-streaming live in the cockpit endpoints.
This keeps the architecture identical to nexus.work_queue: a pure, import-safe,
unit-testable module that the endpoint layer calls into.

Prompt design principles (ratified 2026-06-25):
  • Eye-level, emotionally honest Hebrew — not therapist-speak, not kitsch.
  • Short: WhatsApp length, 1-3 sentences almost always enough.
  • Grounded in the ACTUAL conversation — never invent facts.
  • Human voice: Erez is a real person, not a brand.
  • Move forward: every draft should advance toward a concrete next step.
"""

# ── Prompt persona ─────────────────────────────────────────────────────────────
# Gemini receives this as the opening of every draft prompt. It must be
# byte-stable so Gemini's KV cache (where available) benefits on repeated
# requests for the same lead.

PERSONA = (
    "אתה עוזר הכתיבה האישי של ארז גרטסמן, מטפל זוגי ומשפחתי. "
    "אתה כותב בשמו תגובות WhatsApp אנושיות ואמיתיות — לא טקסטי תרפיסט, "
    "לא שפה קלינית, לא קלישאות. ארז הוא אדם אמיתי שמגיב לאנשים שמחפשים עזרה. "
    "הדרפט שתכתוב הוא הצעה בלבד — ארז יקרא, יערוך ויחליט בעצמו."
)

DRAFTING_RULES = """\
כללי הכתיבה (לא לסטות מהם):
1. כתוב עברית אלא אם הלקוח כתב בשפה אחרת.
2. כתוב בגוף ראשון, בשם ארז — "היי, ארז כאן" אם זו ההתחלה; אחרת ישירות לעניין.
3. קצר. WhatsApp. 1-3 משפטים. לא מאמר.
4. גובה עיניים — לא מלמעלה, לא פסיכולוגיה, לא הדרכה עצמית.
5. בסס על מה שהם כתבו בפועל. אל תמציא פרטים, מחירים, זמינות או הבטחות.
6. אם הצעד הבא לוגיסטי (לינק לתיאום, שאלה על זמין) — עשה אותו בפשטות.
7. אם ההודעה האחרונה כבדה (פחד, אשמה, אובדן) — משפט אחד שמכיר בזה לפני שמתקדמים.
8. אין אמוג'ים אלא אם הלקוח השתמש בהם. אין "אני ממש מבין את הכאב שלך".
9. אל תציין שאתה AI, שזה דרפט, או שיש מישהו שיחזור. פשוט כתוב את ההודעה.
10. פלט: רק טקסט ההודעה. ללא ציטוטים, ללא תוויות, ללא הסברים.
"""

# Thread context budget — enough to draft well, small enough to stay fast.
THREAD_LIMIT = 30

# ── Tool schema (defined here; WS4 ⌘K wires these to actuators) ───────────────
COPILOT_TOOLS = [
    {
        "name": "draft_reply",
        "description": (
            "Draft a WhatsApp reply for Erez to review and send. "
            "NEVER sends — only proposes text the human approves."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The drafted reply in the lead's language (Hebrew by default).",
                },
                "rationale": {
                    "type": "string",
                    "description": "One short line: why this reply, grounded in the thread.",
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    },
]

# ── Pure context-formatting helpers ───────────────────────────────────────────

_ROLE_LABEL = {
    "user": "לקוח",
    "assistant": "הודעה אוטומטית",
    "operator": "ארז",
}


def format_person360(person: dict) -> str:
    """Compact, stable Person-360 block for the draft prompt."""
    name = (person.get("name") or "לקוח לא מזוהה").strip()
    lines = [f"שם: {name}"]
    if person.get("stage"):
        lines.append(f"שלב: {person['stage']}")
    if person.get("essence"):
        lines.append(f"מהות (ניתוח AI): {person['essence']}")
    if person.get("goal"):
        lines.append(f"מטרה: {person['goal']}")
    if person.get("tension"):
        lines.append(f"מתח: {person['tension']}")
    if person.get("topic"):
        lines.append(f"נושא אחרון: {person['topic']}")
    return "\n".join(lines)


def format_thread(messages: list, limit: int = THREAD_LIMIT) -> str:
    """Render the WhatsApp thread oldest→newest as a readable transcript."""
    recent = messages[-limit:] if limit and len(messages) > limit else list(messages)
    if not recent:
        return "(אין היסטוריית שיחה)"
    lines = []
    for m in recent:
        label = _ROLE_LABEL.get(m.get("role", ""), m.get("role", "?"))
        body = (m.get("body") or "").strip()
        if body:
            lines.append(f"{label}: {body}")
    return "\n".join(lines) if lines else "(אין היסטוריית שיחה)"


def build_context_envelope(person: dict, thread: list) -> str:
    """The cached per-person context block: Person-360 + conversation transcript."""
    return (
        "=== פרטי הלקוח ===\n"
        f"{format_person360(person)}\n\n"
        "=== השיחה (מהישן לחדש) ===\n"
        f"{format_thread(thread)}"
    )


def build_draft_prompt(person: dict, thread: list, intent: str = None) -> str:
    """
    Full Gemini prompt for a reply draft: persona → rules → context → instruction.
    The instruction is the only volatile part; everything before it is byte-stable
    across repeated calls on the same lead (benefits from Gemini's response cache).
    """
    instruction = (intent or "").strip()
    if not instruction:
        instruction = "כתוב את ההודעה הבאה של ארז לשיחה הזו."
    else:
        instruction = f"הנחיית ארז: {instruction}\nכתוב את ההודעה בהתאם."

    return (
        f"{PERSONA}\n\n"
        f"{DRAFTING_RULES}\n"
        f"{build_context_envelope(person, thread)}\n\n"
        f"{instruction}"
    )


# ── Demo-mode fallback draft (pre-baked Hebrew, used when no DB data exists) ───
# The stream endpoint uses this when the person has no essay / thread data so the
# demo always shows impressive output even against a cold or sparse database.

def demo_draft_for(person: dict) -> str:
    """Return a high-quality pre-baked Hebrew draft keyed on pipeline stage."""
    stage = (person.get("stage") or "").lower()
    name_first = (person.get("name") or "").split()[0] if person.get("name") else ""
    greeting = f"היי {name_first}, " if name_first else "היי, "

    if "booked" in stage:
        return (
            f"{greeting}ארז כאן. רק רציתי לאשר שאנחנו נפגשים — "
            "תוכלי לשלוח לי תזכורת קצרה ביום לפני? מחכה לשיחה."
        )
    if "captured" in stage or "briefed" in stage:
        return (
            f"{greeting}ארז כאן. קראתי את מה שכתבת ואני מבין — "
            "זה לא מקום פשוט להיות בו. "
            "הנה הלינק לתיאום שיחה ראשונה: [קישור]. יש לי מקום השבוע."
        )
    if "qualified" in stage:
        return (
            f"{greeting}ארז כאן. רציתי לבדוק — "
            "עדיין חושב על זה? אם כן, נדבר. "
            "לא צריך להחליט שום דבר עכשיו."
        )
    # Default: engaged / unknown
    return (
        f"{greeting}ארז כאן. ראיתי שפנית, וזה לוקח אומץ. "
        "אם תרצה לדבר, אני כאן — בלי לחץ."
    )
