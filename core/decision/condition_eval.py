"""DEC-5.13-5.17: evaluating a condition tree against effective evidence.

Three-valued, not boolean. DEC-5.17.1 ("indeterminate evidence MUST NOT
collapse into boolean truth where that could produce unsafe VERIFIED") and
DEC-5.17.2 ("policy schema MUST define INCONCLUSIVE, unavailable, and
invalid behavior under negation") cannot both be satisfied by a predicate
that only returns True/False: under two-valued logic, "we could not
determine whether X" becomes False, and `Not(X)` then becomes True -- which
is precisely the collapse DEC-5.17.1 forbids. So absence, an unset field, an
unresolvable threshold, and an incomparable operand all produce
INDETERMINATE, and INDETERMINATE propagates through negation unchanged.

Gates and rules match only on TRUE. INDETERMINATE never fires anything, in
either direction.
"""

import operator
from enum import StrEnum
from typing import Any

from core.decision.context import EffectiveEvidenceSet
from core.policy.condition import (
    AllOf,
    AnyOf,
    Condition,
    ConditionOperand,
    EvidenceCondition,
    Not,
    ThresholdRef,
)
from core.policy.thresholds import ThresholdDefinition


class TruthValue(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    INDETERMINATE = "INDETERMINATE"


_OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}

# Sentinel distinguishing "this field resolved to the value None" from "this
# field did not resolve at all". EVD-3.6.4 forbids null or a missing field
# from substituting for a defined evidence state, so both collapse to
# INDETERMINATE -- but the distinction is worth keeping explicit in code.
_UNRESOLVED = object()


def _of(value: bool) -> TruthValue:
    return TruthValue.TRUE if value else TruthValue.FALSE


def _resolve_field(result: Any, field: str) -> Any:
    """The evidence-side operand. `status`/`score`/`quality` are universal
    EvidenceResult attributes; anything else is looked up in the result
    payload."""
    if field == "status":
        return result.status.value
    if field == "score":
        return _UNRESOLVED if result.score is None else result.score
    if field == "quality":
        return _UNRESOLVED if result.quality is None else result.quality
    payload = result.result
    if payload is None or field not in payload:
        return _UNRESOLVED
    value = payload[field]
    return _UNRESOLVED if value is None else value


def _resolve_operand(expected: ConditionOperand, thresholds: dict[str, ThresholdDefinition]) -> Any:
    """The policy-side operand. A ThresholdRef resolves to its definition's
    value; policy validation already guarantees the definition exists and
    applies to this evidence type, so an unresolvable name here means the
    policy is internally inconsistent -- INDETERMINATE rather than a crash,
    since the engine must never fail open."""
    if isinstance(expected, ThresholdRef):
        definition = thresholds.get(expected.name)
        return _UNRESOLVED if definition is None else definition.value
    return expected


def _compare(actual: Any, op: str, expected: Any) -> TruthValue:
    # bool is a subclass of int in Python, so `True == 1` and `True >= 0.5`
    # both evaluate without error. A boolean operand and a numeric one are
    # not the same kind of thing, and silently coercing between them is
    # exactly the sort of accidental truth DEC-5.17.1 is about.
    if isinstance(actual, bool) != isinstance(expected, bool):
        if op == "==":
            return TruthValue.FALSE
        if op == "!=":
            return TruthValue.TRUE
        return TruthValue.INDETERMINATE
    try:
        return _of(bool(_OPERATORS[op](actual, expected)))
    except TypeError:
        # Incomparable operands, e.g. a string status against a float
        # threshold. Undetermined, never "not equal" and never False.
        return TruthValue.INDETERMINATE


def _evaluate_leaf(
    leaf: EvidenceCondition,
    *,
    evidence_set: EffectiveEvidenceSet,
    thresholds: dict[str, ThresholdDefinition],
) -> TruthValue:
    expected = _resolve_operand(leaf.expected_value, thresholds)
    if expected is _UNRESOLVED:
        return TruthValue.INDETERMINATE

    if leaf.field == "_present":
        # Presence is always decidable: either an effective result of this
        # type exists for the session or it does not. This is the one field
        # legal against a PROHIBITED evidence type, and the only channel
        # through which prohibited evidence may affect an outcome.
        return _compare(evidence_set.is_present(leaf.evidence_type), leaf.operator, expected)

    result = evidence_set.by_type.get(leaf.evidence_type)
    if result is None:
        # Absent, undeclared, or prohibited evidence. Nothing was observed,
        # so nothing is true *or* false about it (DEC-5.17.1).
        return TruthValue.INDETERMINATE

    actual = _resolve_field(result, leaf.field)
    if actual is _UNRESOLVED:
        return TruthValue.INDETERMINATE
    return _compare(actual, leaf.operator, expected)


def evaluate_condition(
    condition: Condition,
    *,
    evidence_set: EffectiveEvidenceSet,
    thresholds: dict[str, ThresholdDefinition],
) -> TruthValue:
    """Kleene three-valued evaluation of a condition tree.

    `AllOf`: FALSE if any child is FALSE (a known failure is decisive even
    if siblings are unknown), else INDETERMINATE if any child is, else TRUE.
    `AnyOf`: the mirror image. `Not`: swaps TRUE and FALSE and leaves
    INDETERMINATE alone -- the single rule DEC-5.17 is about.
    """
    if isinstance(condition, EvidenceCondition):
        return _evaluate_leaf(condition, evidence_set=evidence_set, thresholds=thresholds)

    if isinstance(condition, AllOf):
        children = [
            evaluate_condition(child, evidence_set=evidence_set, thresholds=thresholds)
            for child in condition.all_of
        ]
        if TruthValue.FALSE in children:
            return TruthValue.FALSE
        if TruthValue.INDETERMINATE in children:
            return TruthValue.INDETERMINATE
        return TruthValue.TRUE

    if isinstance(condition, AnyOf):
        children = [
            evaluate_condition(child, evidence_set=evidence_set, thresholds=thresholds)
            for child in condition.any_of
        ]
        if TruthValue.TRUE in children:
            return TruthValue.TRUE
        if TruthValue.INDETERMINATE in children:
            return TruthValue.INDETERMINATE
        return TruthValue.FALSE

    if isinstance(condition, Not):
        inner = evaluate_condition(
            condition.condition, evidence_set=evidence_set, thresholds=thresholds
        )
        if inner is TruthValue.TRUE:
            return TruthValue.FALSE
        if inner is TruthValue.FALSE:
            return TruthValue.TRUE
        return TruthValue.INDETERMINATE

    raise TypeError(f"unknown condition node type: {type(condition)!r}")
