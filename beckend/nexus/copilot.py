"""
nexus.copilot — P2 "The Ambient Copilot" Reasoning Core (ratified 2026-06-25).

The Claude seam that drafts / summarizes / reasons ON TOP of the deterministic
Work Queue engine. This is the NARRATION + DRAFTING layer, never a competing
ranker — nexus.work_queue stays the spine. The Copilot is Erez's instrument:
it drafts and the Human disposes. It NEVER sends outbound on its own (honors the
WhatsApp intake-assistant pivot). The crisis gate stays upstream in main.py and
is never touched here.

Two model tiers (ratified):
  • MODEL_DRAFT (claude-opus-4-8)  — reply drafts + multi-step reasoning.
  • MODEL_FAST  (claude-haiku-4-5) — instant nudges, summaries, confidence notes.

Like nexus.db, this module never imports main (that would be circular). main.py
calls configure() once at import with the API key + timeout. The prompt-assembly
helpers are PURE (no client, no IO) so they unit-test exactly like
nexus.work_queue. The client is lazily built on first use, so an unconfigured
deploy (no key) imports fine and the endpoints fail closed with 503.

Prompt caching: the frozen persona (system) and the per-person context envelope
are the stable cached prefix; the volatile per-turn instruction is appended after
the last cache breakpoint. See shared/prompt-caching.md.
"""

import logging
from typing import Iterator, Optional

logger = logging.getLogger("nexus.copilot")

# ── Model tiers ──────────────────────────────────────────────────────────────
MODEL_DRAFT = "claude-opus-4-8"     # reply drafts + reasoning
MODEL_FAST = "claude-haiku-4-5"     # instant nudges / summaries / confidence notes

MAX_DRAFT_TOKENS = 1024             # a WhatsApp reply is short; plenty of headroom
MAX_FAST_TOKENS = 512              # nudges / summaries are one or two sentences

# Thread context budget — the most recent N messages are enough to draft well and
# keeps the cached envelope small. Oldest dropped first (chronology preserved).
THREAD_CONTEXT_LIMIT = 40


# ── The frozen persona (the stable, cacheable system prompt) ──────────────────
# IMPORTANT: this string must stay byte-stable to remain a cache hit — no
# datetime, no uuid, no per-request interpolation. All volatile context goes in
# the user message (the context envelope + the per-turn instruction).
SYSTEM_PROMPT = (
    "You are NEXUS Copilot — Erez's private drafting assistant inside his command "
    "center. Erez is a relationship & couples consultant. People reach out to him on "
    "WhatsApp, often in the middle of a real crisis. The automated WhatsApp line only "
    "sends ONE transparent handoff message and then goes silent — Erez reads every "
    "thread and replies personally. Your job is to help him write those personal "
    "replies faster and better.\n"
    "\n"
    "You are an instrument, not the voice. You draft; Erez reviews every word and "
    "sends it himself. You never send anything, never promise that a message was "
    "sent, and never speak directly to the lead.\n"
    "\n"
    "How to draft:\n"
    "• Write AS Erez, in the first person — a real person texting back, not a brand or "
    "a bot.\n"
    "• Match the lead's language. They almost always write Hebrew; draft in Hebrew "
    "unless they clearly wrote in another language.\n"
    "• Warm, direct, human. Short — WhatsApp length, a few sentences at most. No "
    "clinical 'therapist-speak', no generic self-help advice, no emoji unless the "
    "lead's own tone invites it.\n"
    "• Ground every word in the actual conversation and what we know about this "
    "person (their goal, their tension, their essence). Never invent facts, prices, "
    "availability, or promises.\n"
    "• When the next move is logistical (a time, a link, a question), make the draft "
    "move it one concrete step forward.\n"
    "\n"
    "Safety: if the latest messages show a self-harm or acute-crisis signal, do NOT "
    "draft a casual reply. Say plainly that this needs Erez's personal, immediate "
    "attention and stop. Never minimize it."
)


# ── Tool schema (defined now; the WS4 ⌘K agentic loop wires these to actuators) ─
# Raw JSON schema (not @beta_tool) so the verbs are explicit and the human-approval
# gate on `send` lives in the UI layer, never here. draft_reply is the WS2 core;
# summarize / snooze round out the verb set the command palette will expose.
COPILOT_TOOLS = [
    {
        "name": "draft_reply",
        "description": (
            "Draft a WhatsApp reply for Erez to review and send. This NEVER sends — "
            "it only proposes text the human approves."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": (
                        "The drafted reply, written as Erez in the lead's language "
                        "(Hebrew unless they wrote otherwise)."
                    ),
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
    {
        "name": "summarize",
        "description": "Summarize where this conversation stands and the single best next move.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Two or three sentences, plain language."},
                "next_move": {"type": "string", "description": "The one concrete next action for Erez."},
            },
            "required": ["summary", "next_move"],
            "additionalProperties": False,
        },
    },
    {
        "name": "snooze",
        "description": "Suggest deferring this lead, with how long and why.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "number", "description": "How many hours to defer."},
                "reason": {"type": "string", "description": "Why deferring is the right call now."},
            },
            "required": ["hours", "reason"],
            "additionalProperties": False,
        },
    },
]


# ── Pure prompt-assembly helpers (no client, no IO — unit-tested like work_queue) ─

def format_person360(person: dict) -> str:
    """Render the memory-first Person-360 into a compact, stable context block."""
    name = (person.get("name") or "Unknown lead").strip()
    lines = [f"Lead: {name}"]
    if person.get("channel"):
        handle = person.get("handle")
        lines.append(f"Channel: {person['channel']}" + (f" ({handle})" if handle else ""))
    if person.get("stage"):
        lines.append(f"Pipeline stage: {person['stage']}")
    if person.get("essence"):
        lines.append(f"Essence: {person['essence']}")
    if person.get("goal"):
        lines.append(f"Goal: {person['goal']}")
    if person.get("tension"):
        lines.append(f"Tension: {person['tension']}")
    if person.get("topic"):
        lines.append(f"Last session topic: {person['topic']}")
    if person.get("emotional_state"):
        lines.append(f"Emotional state: {person['emotional_state']}")
    return "\n".join(lines)


_ROLE_LABEL = {
    "user": "Lead",
    "assistant": "Auto handoff",   # the one-time transparent ACK the bot sent
    "operator": "Erez",
}


def format_thread(messages: list, limit: int = THREAD_CONTEXT_LIMIT) -> str:
    """
    Render the merged WhatsApp thread (oldest→newest) into a readable transcript.
    Keeps only the most recent `limit` turns (oldest dropped first). Each message
    is a dict {role, body, at}; unknown roles fall back to their raw label.
    """
    recent = messages[-limit:] if limit and len(messages) > limit else list(messages)
    if not recent:
        return "(no conversation on record yet)"
    lines = []
    for m in recent:
        label = _ROLE_LABEL.get(m.get("role", ""), m.get("role", "?"))
        body = (m.get("body") or "").strip()
        if body:
            lines.append(f"{label}: {body}")
    return "\n".join(lines) if lines else "(no conversation on record yet)"


def build_context_envelope(person: dict, thread: list, limit: int = THREAD_CONTEXT_LIMIT) -> str:
    """
    The stable, per-person context block — the cached prefix the draft is grounded
    in. Person-360 first (slowest-changing), then the conversation transcript.
    """
    return (
        "=== WHO YOU'RE HELPING EREZ REPLY TO ===\n"
        f"{format_person360(person)}\n\n"
        "=== THE CONVERSATION SO FAR (oldest first) ===\n"
        f"{format_thread(thread, limit=limit)}"
    )


def build_instruction(intent: Optional[str]) -> str:
    """
    The volatile per-turn instruction, appended AFTER the cached prefix. Empty
    intent → draft the natural next reply; otherwise honor the operator's steer.
    """
    intent = (intent or "").strip()
    if not intent:
        return (
            "Draft Erez's next WhatsApp reply to this lead. Output ONLY the message "
            "text he would send — no preamble, no quotes, no notes."
        )
    return (
        f"Erez's instruction: {intent}\n"
        "Draft the WhatsApp reply accordingly. Output ONLY the message text he would "
        "send — no preamble, no quotes, no notes."
    )


# ── The Claude client seam (lazy; configured by main.py, mirrors nexus.db) ─────

class CopilotUnavailable(RuntimeError):
    """Raised when the Copilot is called but no Anthropic key is configured."""


_api_key: str = ""
_timeout: float = 60.0
_client = None  # lazily built anthropic.Anthropic instance


def configure(api_key: str, timeout: float = 60.0) -> None:
    """Install the Anthropic API key + per-call timeout (called once by main.py)."""
    global _api_key, _timeout, _client
    _api_key = api_key or ""
    _timeout = timeout
    _client = None  # force a rebuild on next use


def is_available() -> bool:
    """True when an Anthropic key is configured (the endpoints gate on this)."""
    return bool(_api_key)


def _get_client():
    """Build (once) and return the Anthropic client. Raises if unconfigured."""
    global _client
    if not _api_key:
        raise CopilotUnavailable(
            "Copilot is not configured — set ANTHROPIC_API_KEY in the backend env."
        )
    if _client is None:
        import anthropic  # imported lazily so an unconfigured deploy never needs the dep at import
        _client = anthropic.Anthropic(api_key=_api_key, timeout=_timeout)
    return _client


def _system_blocks() -> list:
    """The frozen persona as a cache-controlled system block (global cache hit)."""
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def _draft_messages(person: dict, thread: list, intent: Optional[str]) -> list:
    """
    One user turn: the cached per-person context envelope (cache breakpoint), then
    the volatile instruction. Keeping the envelope as its own block lets repeated
    drafts on the SAME lead within the 5-minute window hit the cache.
    """
    return [{
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": build_context_envelope(person, thread),
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": build_instruction(intent)},
        ],
    }]


def stream_reply_draft(
    person: dict,
    thread: list,
    intent: Optional[str] = None,
    *,
    model: str = MODEL_DRAFT,
) -> Iterator[str]:
    """
    Stream a reply draft token-by-token (the SSE source for the cockpit composer).
    Yields visible text deltas only. No extended thinking — a warm, short reply
    needs a fast first token, and the context envelope already does the reasoning
    work. The deeper "reason about this lead" path can opt into adaptive thinking.

    Raises CopilotUnavailable if no key is configured (the endpoint maps to 503).
    """
    client = _get_client()
    with client.messages.stream(
        model=model,
        max_tokens=MAX_DRAFT_TOKENS,
        system=_system_blocks(),
        messages=_draft_messages(person, thread, intent),
    ) as stream:
        for text in stream.text_stream:
            yield text


def _call_claude(
    user_text: str,
    *,
    system: Optional[str] = None,
    model: str = MODEL_FAST,
    max_tokens: int = MAX_FAST_TOKENS,
) -> str:
    """
    The non-streaming seam — the Claude analogue of main.py's _call_llm (Gemini).
    Used for instant, short outputs (nudges, summaries, confidence notes). The
    SDK enforces the configured timeout and auto-retries 429/5xx.

    Raises CopilotUnavailable if no key is configured.
    """
    client = _get_client()
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_text}],
    }
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def summarize_thread(person: dict, thread: list) -> str:
    """
    A fast Haiku summary of where the conversation stands + the next move. Plain
    text (one short paragraph). Used by nudges and the ⌘K 'catch me up' verb.
    """
    user = (
        build_context_envelope(person, thread)
        + "\n\nIn 2-3 sentences, tell Erez where this conversation stands and the "
        "single best next move. Plain language, no preamble."
    )
    return _call_claude(user, system=SYSTEM_PROMPT, model=MODEL_FAST)
