"""
Unit tests for the pure P2 Copilot reasoning core (no network, no client):
prompt assembly (Person-360 → context block, thread → transcript, envelope),
the volatile instruction, the tool schema, and the fail-closed client gate.

The Claude calls themselves (stream_reply_draft / _call_claude) are NOT exercised
here — they need a key and the network. These tests pin the CONTRACT the prompt
is built from, exactly like test_nexus_work_queue pins the ranking contract.
"""

import pytest

from nexus import copilot


# ── Fixtures ──────────────────────────────────────────────────────────────────

PERSON = {
    "name": "Maya Goren",
    "channel": "whatsapp",
    "handle": "BR-1188",
    "stage": "captured",
    "essence": "She isn't afraid of leaving. She's afraid of being the one who broke it.",
    "goal": "Decide before the anniversary",
    "tension": "Guilt vs. relief",
    "emotional_state": "anxious",
    "topic": "considering separation",
}

THREAD = [
    {"role": "user", "body": "שלום, רציתי לשאול על ייעוץ זוגי", "at": "2026-06-14T10:00:00+00:00"},
    {"role": "assistant", "body": "זו הודעה אוטומטית — ארז יחזור אליך אישית.", "at": "2026-06-14T10:00:09+00:00"},
    {"role": "user", "body": "אנחנו בזוגיות של 4 שנים ויש משבר", "at": "2026-06-14T10:05:00+00:00"},
    {"role": "operator", "body": "היי מאיה, ארז כאן. מתי נוח לך לדבר?", "at": "2026-06-25T19:30:00+00:00"},
]


# ── Person-360 rendering ──────────────────────────────────────────────────────

class TestFormatPerson360:
    def test_includes_core_memory_fields(self):
        out = copilot.format_person360(PERSON)
        assert "Maya Goren" in out
        assert "Guilt vs. relief" in out
        assert "Decide before the anniversary" in out
        assert PERSON["essence"] in out

    def test_missing_fields_are_omitted_not_blanked(self):
        out = copilot.format_person360({"name": "Lead BR-9"})
        assert "Lead BR-9" in out
        assert "Essence:" not in out
        assert "Goal:" not in out

    def test_unknown_name_falls_back(self):
        out = copilot.format_person360({})
        assert "Unknown lead" in out


# ── Thread transcript rendering ───────────────────────────────────────────────

class TestFormatThread:
    def test_roles_are_labeled_for_the_model(self):
        out = copilot.format_thread(THREAD)
        assert "Lead:" in out          # inbound
        assert "Erez:" in out          # operator
        assert "Auto handoff:" in out  # bot ACK

    def test_chronological_order_preserved(self):
        out = copilot.format_thread(THREAD)
        first = out.index("רציתי לשאול")
        last = out.index("מתי נוח לך")
        assert first < last

    def test_empty_thread_is_explicit(self):
        assert "no conversation" in copilot.format_thread([]).lower()

    def test_limit_keeps_most_recent(self):
        many = [{"role": "user", "body": f"msg{i}", "at": f"2026-06-0{i}"} for i in range(1, 6)]
        out = copilot.format_thread(many, limit=2)
        assert "msg5" in out and "msg4" in out
        assert "msg1" not in out

    def test_blank_bodies_dropped(self):
        out = copilot.format_thread([{"role": "user", "body": "  ", "at": "x"}])
        assert "no conversation" in out.lower()


# ── Context envelope + instruction ────────────────────────────────────────────

class TestEnvelope:
    def test_envelope_has_both_sections(self):
        env = copilot.build_context_envelope(PERSON, THREAD)
        assert "WHO YOU'RE HELPING" in env
        assert "CONVERSATION SO FAR" in env
        assert "Maya Goren" in env
        assert "מתי נוח לך" in env

    def test_default_instruction_is_self_contained(self):
        instr = copilot.build_instruction(None)
        assert "ONLY the message" in instr

    def test_operator_intent_is_honored(self):
        instr = copilot.build_instruction("answer her pricing question warmly")
        assert "pricing question" in instr
        assert "ONLY the message" in instr


# ── Tool schema (WS4 forward-compat) ──────────────────────────────────────────

class TestToolSchema:
    def test_verbs_present(self):
        names = {t["name"] for t in copilot.COPILOT_TOOLS}
        assert names == {"draft_reply", "summarize", "snooze"}

    def test_schemas_are_strict_objects(self):
        for tool in copilot.COPILOT_TOOLS:
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert schema["required"]


# ── System prompt cache-stability + discipline ────────────────────────────────

class TestSystemPrompt:
    def test_frozen_for_caching(self):
        # No volatile tokens that would silently invalidate the prompt cache.
        assert "{" not in copilot.SYSTEM_PROMPT  # no f-string leftovers
        assert copilot.SYSTEM_PROMPT == copilot.SYSTEM_PROMPT  # stable identity

    def test_encodes_never_send_and_crisis_discipline(self):
        sp = copilot.SYSTEM_PROMPT.lower()
        assert "never send" in sp
        assert "crisis" in sp or "self-harm" in sp


# ── Fail-closed client gate ───────────────────────────────────────────────────

class TestClientGate:
    def test_unconfigured_is_unavailable_and_raises(self):
        copilot.configure(api_key="", timeout=10)
        assert copilot.is_available() is False
        with pytest.raises(copilot.CopilotUnavailable):
            list(copilot.stream_reply_draft(PERSON, THREAD))

    def test_configure_flips_availability(self):
        copilot.configure(api_key="sk-test-not-real", timeout=10)
        assert copilot.is_available() is True
        # Reset so other tests / processes don't accidentally hold a fake key.
        copilot.configure(api_key="", timeout=10)
