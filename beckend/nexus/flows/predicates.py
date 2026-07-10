"""
nexus.flows.predicates — the safe condition DSL for Flow `condition` nodes
(SYSTEM_ELEVATION_PRD.md §B4: "a JSONB predicate DSL, evaluated by a safe
interpreter... Never free-form code").

A predicate is a small JSON tree over a TYPED field registry:

    {"field": "stage", "op": "eq", "value": "qualified"}
    {"all": [pred, pred, ...]}
    {"any": [pred, pred, ...]}
    {"not": pred}

Fields come from FIELD_REGISTRY — anything else is a hard PredicateError, both
at validation time (F3 publish-gate) and at evaluation time. A malformed flow
must never silently evaluate to False; that would masquerade as "the
condition just hasn't been true yet" instead of the bug it is.

Pure — no DB, no I/O. Mirrors nexus.work_queue's pure decide-from-signals
shape: callers fetch a `signals` dict (see nexus.flows.signals), this module
only ever reasons about that dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class PredicateError(ValueError):
    """A malformed predicate — unknown field/op, or a bad tree shape."""


@dataclass(frozen=True)
class Field:
    name: str
    type: str   # 'string' | 'number' | 'bool'
    description: str


# The ONLY signals a condition node may reference — mirrors
# nexus.work_queue.Signals (stage/hours_since_last/urgency), extended with the
# couple of fields flows additionally need. Extend deliberately; every new
# field must be a real, already-computed value (nexus/flows/signals.py), never
# a live query triggered from inside a predicate.
FIELD_REGISTRY: dict[str, Field] = {
    "stage":            Field("stage", "string", "opportunities.stage"),
    "hours_since_last":  Field("hours_since_last", "number", "hours since the last interaction"),
    "hours_in_stage":    Field("hours_in_stage", "number", "hours since the current stage began"),
    "channel":           Field("channel", "string", "opportunities.source_channel"),
    "urgency":           Field("urgency", "number", "latest session urgency, 1-10 (reserved, V2)"),
    "waiting_on":        Field("waiting_on", "string", "operator | lead | untouched (reserved, V2)"),
}

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq":  lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt":  lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt":  lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "in":  lambda a, b: a in (b or []),
}

_COMBINATORS = ("all", "any", "not")


def validate(predicate: dict) -> None:
    """Walk the tree and raise PredicateError on anything malformed, without
    evaluating it. Call at flow publish time (F3) and defensively before any
    evaluate() a dispatcher/runner sweep performs on stored data."""
    _walk(predicate, signals=None)


def evaluate(predicate: dict, signals: dict[str, Any]) -> bool:
    """Evaluate one predicate tree against a signals dict. Raises
    PredicateError on a malformed predicate."""
    return _walk(predicate, signals=signals)


def _walk(node: Any, *, signals: dict[str, Any] | None) -> bool:
    validate_only = signals is None
    if not isinstance(node, dict):
        raise PredicateError(f"predicate node must be an object, got {type(node).__name__}")

    combinators_present = [c for c in _COMBINATORS if c in node]
    if len(combinators_present) > 1:
        raise PredicateError(f"a predicate node may use only one combinator, got {combinators_present}")

    if combinators_present == ["all"]:
        children = node["all"]
        if not isinstance(children, list) or not children:
            raise PredicateError("'all' must be a non-empty list")
        results = [_walk(c, signals=signals) for c in children]
        return True if validate_only else all(results)

    if combinators_present == ["any"]:
        children = node["any"]
        if not isinstance(children, list) or not children:
            raise PredicateError("'any' must be a non-empty list")
        results = [_walk(c, signals=signals) for c in children]
        return True if validate_only else any(results)

    if combinators_present == ["not"]:
        inner = _walk(node["not"], signals=signals)
        return True if validate_only else not inner

    # Leaf: {"field", "op", "value"}
    field = node.get("field")
    op = node.get("op")
    if field not in FIELD_REGISTRY:
        raise PredicateError(f"unknown field {field!r} — not in FIELD_REGISTRY")
    if op not in _OPS:
        raise PredicateError(f"unknown op {op!r}")
    if "value" not in node:
        raise PredicateError(f"leaf predicate on field {field!r} is missing 'value'")
    if validate_only:
        return True
    actual = (signals or {}).get(field)
    return _OPS[op](actual, node.get("value"))
