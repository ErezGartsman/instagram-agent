"""
Unit tests for the pure logic in the nexus package (no DB required):
phone normalization, wa_ref generation, and pipeline stage ordering.
DB-touching functions (resolve_or_create_person, advance_stage, …) are
covered by integration smoke checks at wiring time (ticket 3.3/3.7).
"""

import pytest

from nexus.identity import (
    _WA_REF_ALPHABET,
    _WA_REF_LENGTH,
    generate_wa_ref,
    normalize_phone,
)
from nexus.interactions import (
    INTERACTION_KINDS,
    PIPELINE_STAGES,
    TERMINAL_STAGES,
    stage_is_forward,
)


class TestNormalizePhone:
    @pytest.mark.parametrize("raw,expected", [
        # Israeli local forms → +972
        ("0501234567",        "+972501234567"),
        ("050-123 4567",      "+972501234567"),
        ("050-1234567",       "+972501234567"),
        # Already international (Telegram contact-share forms)
        ("+972501234567",     "+972501234567"),
        ("972501234567",      "+972501234567"),
        ("00972501234567",    "+972501234567"),
        # Foreign numbers with explicit country code pass through
        ("+1 415 555 1234",   "+14155551234"),
        ("14155551234",       "+14155551234"),
    ])
    def test_normalizes(self, raw, expected):
        assert normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", [
        None, "", "abc", "12345",
        "05012345",      # too short for an Israeli local number
        "4155551234",    # bare 10-digit, no leading 0 — ambiguous country, reject
        "+",
    ])
    def test_rejects_ambiguous(self, raw):
        assert normalize_phone(raw) is None

    def test_never_guesses(self):
        # The contract: None means "do not link" — wrong joins corrupt the
        # cross-channel identity key, so ambiguity must never normalize.
        assert normalize_phone("123456789012345678") is None  # > 15 digits


class TestWaRef:
    def test_shape(self):
        code = generate_wa_ref()
        assert len(code) == _WA_REF_LENGTH
        assert all(c in _WA_REF_ALPHABET for c in code)

    def test_no_ambiguous_characters(self):
        assert not set("0O1I") & set(_WA_REF_ALPHABET)

    def test_practically_unique(self):
        codes = {generate_wa_ref() for _ in range(200)}
        assert len(codes) == 200


class TestStageMachine:
    def test_forward_moves(self):
        assert stage_is_forward("engaged", "qualified")
        assert stage_is_forward("engaged", "captured")
        assert stage_is_forward("captured", "briefed")
        # booked is reachable from any open stage (engaged → Calendly direct)
        assert stage_is_forward("engaged", "booked")

    def test_regressions_and_repeats_blocked(self):
        assert not stage_is_forward("captured", "engaged")
        assert not stage_is_forward("booked", "captured")
        assert not stage_is_forward("engaged", "engaged")

    def test_unknown_stages_fail_closed(self):
        assert not stage_is_forward("nope", "captured")
        assert not stage_is_forward("engaged", "nope")
        # terminal stages are not pipeline moves — they go via close_opportunity
        assert not stage_is_forward("engaged", "done")
        assert not stage_is_forward("done", "lost")

    def test_constants_sane(self):
        assert PIPELINE_STAGES[0] == "engaged"
        assert PIPELINE_STAGES[-1] == "booked"
        assert set(TERMINAL_STAGES) == {"done", "lost"}
        assert "stage_change" in INTERACTION_KINDS
