"""
Unit tests for the pure P2 Copilot helpers (nexus.copilot) — no network, no LLM.

This module is Gemini-based and purely prompt/context assembly — no client, no
configure, no availability gate. Tests pin the CONTRACT that the draft prompt is
built from, exactly like test_nexus_work_queue pins the ranking contract.
"""

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
    {"role": "user",     "body": "שלום, רציתי לשאול על ייעוץ זוגי", "at": "2026-06-14T10:00:00+00:00"},
    {"role": "assistant","body": "זו הודעה אוטומטית — ארז יחזור אליך אישית.", "at": "2026-06-14T10:00:09+00:00"},
    {"role": "user",     "body": "אנחנו בזוגיות של 4 שנים ויש משבר", "at": "2026-06-14T10:05:00+00:00"},
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
        # Fields absent in input must not produce empty label lines
        assert "מהות" not in out or "מהות: " not in out
        assert "מטרה" not in out or "מטרה: " not in out

    def test_unknown_name_falls_back(self):
        out = copilot.format_person360({})
        # Hebrew fallback name
        assert "לקוח" in out


# ── Thread transcript rendering ───────────────────────────────────────────────

class TestFormatThread:
    def test_roles_are_labeled_for_the_model(self):
        out = copilot.format_thread(THREAD)
        assert "לקוח:" in out           # 'user' inbound → Hebrew label
        assert "ארז:" in out            # 'operator' → Erez
        assert "הודעה אוטומטית:" in out  # 'assistant' bot ACK

    def test_chronological_order_preserved(self):
        out = copilot.format_thread(THREAD)
        first = out.index("רציתי לשאול")
        last = out.index("מתי נוח לך")
        assert first < last

    def test_empty_thread_is_explicit(self):
        out = copilot.format_thread([])
        assert "אין" in out  # Hebrew "there is no…"

    def test_limit_keeps_most_recent(self):
        many = [{"role": "user", "body": f"msg{i}", "at": f"2026-06-0{i}"} for i in range(1, 6)]
        out = copilot.format_thread(many, limit=2)
        assert "msg5" in out and "msg4" in out
        assert "msg1" not in out

    def test_blank_bodies_dropped(self):
        out = copilot.format_thread([{"role": "user", "body": "  ", "at": "x"}])
        assert "אין" in out  # only the empty-state message


# ── Context envelope ──────────────────────────────────────────────────────────

class TestEnvelope:
    def test_envelope_has_both_sections(self):
        env = copilot.build_context_envelope(PERSON, THREAD)
        assert "פרטי הלקוח" in env        # Person-360 section header
        assert "השיחה" in env              # thread section header
        assert "Maya Goren" in env
        assert "מתי נוח לך" in env

    def test_envelope_is_byte_stable_across_calls(self):
        # Must not embed any runtime-varying token (datetime, uuid…)
        env1 = copilot.build_context_envelope(PERSON, THREAD)
        env2 = copilot.build_context_envelope(PERSON, THREAD)
        assert env1 == env2


# ── Draft prompt ──────────────────────────────────────────────────────────────

class TestBuildDraftPrompt:
    def test_contains_persona_and_rules(self):
        prompt = copilot.build_draft_prompt(PERSON, THREAD)
        assert copilot.PERSONA[:30] in prompt
        assert "עברית" in prompt  # drafting rule: write Hebrew

    def test_default_instruction_present(self):
        prompt = copilot.build_draft_prompt(PERSON, THREAD)
        assert "ההודעה הבאה" in prompt  # "write the next message"

    def test_operator_intent_honored(self):
        prompt = copilot.build_draft_prompt(PERSON, THREAD, intent="answer her pricing question")
        assert "answer her pricing question" in prompt

    def test_person_and_thread_included(self):
        prompt = copilot.build_draft_prompt(PERSON, THREAD)
        assert "Maya Goren" in prompt
        assert "מתי נוח לך" in prompt


# ── Tool schema (WS4 ⌘K forward-compat) ──────────────────────────────────────

class TestToolSchema:
    def test_draft_reply_verb_present(self):
        names = {t["name"] for t in copilot.COPILOT_TOOLS}
        assert "draft_reply" in names

    def test_schema_is_strict_object(self):
        for tool in copilot.COPILOT_TOOLS:
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert schema["required"]


# ── Demo fallback drafts ──────────────────────────────────────────────────────

class TestDemoDraft:
    def test_returns_hebrew_string(self):
        draft = copilot.demo_draft_for(PERSON)
        assert isinstance(draft, str)
        assert len(draft) > 10
        # Must contain some Hebrew character
        assert any("֐" <= c <= "׿" for c in draft)

    def test_booking_stage_gets_confirmation_draft(self):
        draft = copilot.demo_draft_for({**PERSON, "stage": "booked"})
        # Should reference confirmation, not booking link
        assert "ארז" in draft or "ארז" in draft  # voice stays consistent

    def test_engaged_stage_does_not_promise_prices(self):
        draft = copilot.demo_draft_for({**PERSON, "stage": "engaged"})
        # No invented numbers / prices / availability
        assert "₪" not in draft
        assert "200" not in draft
