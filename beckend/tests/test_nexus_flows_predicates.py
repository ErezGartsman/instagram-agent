"""
tests.test_nexus_flows_predicates — the predicate DSL interpreter. Pure logic,
no mocks needed (pattern A — mirrors test_nexus_work_queue.py).
"""
import pytest

from nexus.flows import predicates


class TestLeaf:
    def test_eq_true(self):
        assert predicates.evaluate({"field": "stage", "op": "eq", "value": "qualified"},
                                   {"stage": "qualified"}) is True

    def test_eq_false(self):
        assert predicates.evaluate({"field": "stage", "op": "eq", "value": "qualified"},
                                   {"stage": "engaged"}) is False

    def test_neq(self):
        assert predicates.evaluate({"field": "stage", "op": "neq", "value": "booked"},
                                   {"stage": "engaged"}) is True

    @pytest.mark.parametrize("op,value,signal,expected", [
        ("gt",  10, 15, True),
        ("gt",  10, 10, False),
        ("gte", 10, 10, True),
        ("lt",  10, 5,  True),
        ("lte", 10, 10, True),
    ])
    def test_numeric_ops(self, op, value, signal, expected):
        pred = {"field": "hours_since_last", "op": op, "value": value}
        assert predicates.evaluate(pred, {"hours_since_last": signal}) is expected

    def test_numeric_op_on_none_is_false_not_a_crash(self):
        """A missing signal (e.g. no interactions yet) must fail the
        comparison cleanly, never raise — a flow condition on an unset field
        is simply not met."""
        pred = {"field": "hours_since_last", "op": "gte", "value": 36}
        assert predicates.evaluate(pred, {"hours_since_last": None}) is False

    def test_in_op(self):
        pred = {"field": "stage", "op": "in", "value": ["qualified", "captured", "briefed"]}
        assert predicates.evaluate(pred, {"stage": "captured"}) is True
        assert predicates.evaluate(pred, {"stage": "engaged"}) is False

    def test_unknown_field_raises(self):
        with pytest.raises(predicates.PredicateError, match="unknown field"):
            predicates.evaluate({"field": "not_a_real_field", "op": "eq", "value": 1}, {})

    def test_unknown_op_raises(self):
        with pytest.raises(predicates.PredicateError, match="unknown op"):
            predicates.evaluate({"field": "stage", "op": "wat", "value": 1}, {"stage": "x"})

    def test_missing_value_raises(self):
        with pytest.raises(predicates.PredicateError, match="missing 'value'"):
            predicates.evaluate({"field": "stage", "op": "eq"}, {"stage": "x"})

    def test_non_dict_node_raises(self):
        with pytest.raises(predicates.PredicateError, match="must be an object"):
            predicates.evaluate("not-a-dict", {})  # type: ignore[arg-type]


class TestCombinators:
    def test_all_true(self):
        pred = {"all": [
            {"field": "stage", "op": "in", "value": ["qualified", "captured", "briefed"]},
            {"field": "hours_since_last", "op": "gte", "value": 36},
        ]}
        assert predicates.evaluate(pred, {"stage": "qualified", "hours_since_last": 40}) is True

    def test_all_short_circuits_to_false(self):
        pred = {"all": [
            {"field": "stage", "op": "eq", "value": "qualified"},
            {"field": "hours_since_last", "op": "gte", "value": 36},
        ]}
        assert predicates.evaluate(pred, {"stage": "qualified", "hours_since_last": 10}) is False

    def test_any_true_if_one_matches(self):
        pred = {"any": [
            {"field": "stage", "op": "eq", "value": "booked"},
            {"field": "stage", "op": "eq", "value": "qualified"},
        ]}
        assert predicates.evaluate(pred, {"stage": "qualified"}) is True

    def test_not_negates(self):
        pred = {"not": {"field": "stage", "op": "eq", "value": "booked"}}
        assert predicates.evaluate(pred, {"stage": "qualified"}) is True
        assert predicates.evaluate(pred, {"stage": "booked"}) is False

    def test_nested_combinators(self):
        pred = {"all": [
            {"field": "channel", "op": "eq", "value": "whatsapp"},
            {"any": [
                {"field": "stage", "op": "eq", "value": "qualified"},
                {"field": "stage", "op": "eq", "value": "captured"},
            ]},
        ]}
        assert predicates.evaluate(pred, {"channel": "whatsapp", "stage": "captured"}) is True
        assert predicates.evaluate(pred, {"channel": "telegram", "stage": "captured"}) is False

    def test_all_empty_list_raises(self):
        with pytest.raises(predicates.PredicateError, match="non-empty"):
            predicates.evaluate({"all": []}, {})

    def test_multiple_combinators_in_one_node_raises(self):
        with pytest.raises(predicates.PredicateError, match="only one combinator"):
            predicates.evaluate({"all": [], "any": []}, {})


class TestValidate:
    def test_validate_does_not_need_signals(self):
        # Should not raise, and should not require a real signals dict.
        predicates.validate({"all": [
            {"field": "stage", "op": "eq", "value": "qualified"},
            {"field": "hours_since_last", "op": "gte", "value": 36},
        ]})

    def test_validate_catches_unknown_field(self):
        with pytest.raises(predicates.PredicateError):
            predicates.validate({"field": "bogus", "op": "eq", "value": 1})

    def test_field_registry_covers_seeded_flow_fields(self):
        # The two F1 seeded flows condition on these — a registry regression
        # here would silently break them.
        for name in ("stage", "hours_since_last"):
            assert name in predicates.FIELD_REGISTRY
