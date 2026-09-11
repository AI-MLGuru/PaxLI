"""DEC-5.13-5.17: three-valued condition evaluation.

Pure, in-memory, no database -- the evaluator is a pure function and these
tests exercise it as one. The single most important case here is
`Not(INDETERMINATE) == INDETERMINATE`: under ordinary boolean logic, absent
evidence would evaluate False and its negation True, which is exactly how an
unsafe VERIFIED gets manufactured out of missing data (DEC-5.17.1).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.decision.condition_eval import TruthValue, evaluate_condition
from core.decision.context import EffectiveEvidenceSet
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult
from core.policy.condition import AllOf, AnyOf, EvidenceCondition, Not, ThresholdRef
from core.policy.thresholds import ThresholdDefinition

SESSION_ID = uuid4()


def _result(
    evidence_type: EvidenceResultType = EvidenceResultType.FACE_MATCH,
    *,
    status: EvidenceResultStatus = EvidenceResultStatus.PASS,
    score: float | None = None,
    quality: float | None = None,
    result: dict | None = None,
) -> EvidenceResult:
    return EvidenceResult(
        tenant_id="tenant-a",
        session_id=SESSION_ID,
        evidence_type=evidence_type,
        status=status,
        score=score,
        quality=quality,
        result=result,
        producer="p",
        producer_version="1",
        produced_at=datetime.now(UTC),
        persisted_at=datetime.now(UTC),
        integrity_reference="ref",
    )


def _set(
    *results: EvidenceResult, prohibited: frozenset[str] = frozenset()
) -> EffectiveEvidenceSet:
    return EffectiveEvidenceSet(
        by_type={r.evidence_type.value: r for r in results},
        prohibited_types_present=prohibited,
    )


def _cond(field: str, operator: str, expected) -> EvidenceCondition:
    return EvidenceCondition(
        evidence_type="FACE_MATCH", field=field, operator=operator, expected_value=expected
    )


def _evaluate(condition, evidence_set, thresholds=None) -> TruthValue:
    return evaluate_condition(condition, evidence_set=evidence_set, thresholds=thresholds or {})


def test_status_comparison_resolves_true_and_false() -> None:
    evidence_set = _set(_result(status=EvidenceResultStatus.PASS))
    assert _evaluate(_cond("status", "==", "PASS"), evidence_set) is TruthValue.TRUE
    assert _evaluate(_cond("status", "==", "FAIL"), evidence_set) is TruthValue.FALSE


def test_absent_evidence_is_indeterminate_not_false() -> None:
    """DEC-5.17.1: nothing was observed, so nothing is true *or* false."""
    assert _evaluate(_cond("status", "==", "PASS"), _set()) is TruthValue.INDETERMINATE


def test_not_of_indeterminate_stays_indeterminate() -> None:
    """The DEC-5.17 rule in one assertion. If absent evidence collapsed to
    False, this would be TRUE and a policy could reach VERIFIED on evidence
    that was never submitted."""
    condition = Not(condition=_cond("status", "==", "FAIL"))
    assert _evaluate(condition, _set()) is TruthValue.INDETERMINATE


def test_not_still_inverts_determinate_values() -> None:
    evidence_set = _set(_result(status=EvidenceResultStatus.PASS))
    assert _evaluate(Not(condition=_cond("status", "==", "PASS")), evidence_set) is TruthValue.FALSE
    assert _evaluate(Not(condition=_cond("status", "==", "FAIL")), evidence_set) is TruthValue.TRUE


def test_unset_score_is_indeterminate_not_zero() -> None:
    """EVD-3.6.4: null or a missing field must not substitute for a defined
    evidence state. A null score compared against >= 0.5 must not be False
    (which would read as 'scored below the threshold')."""
    evidence_set = _set(_result(score=None))
    assert _evaluate(_cond("score", ">=", 0.5), evidence_set) is TruthValue.INDETERMINATE


def test_missing_payload_field_is_indeterminate() -> None:
    evidence_set = _set(_result(result={"similarity": 0.9}))
    condition = _cond("similarity", ">=", 0.5)
    assert _evaluate(condition, evidence_set) is TruthValue.TRUE
    assert _evaluate(_cond("nonexistent", ">=", 0.5), evidence_set) is TruthValue.INDETERMINATE


def test_explicit_null_payload_value_is_indeterminate() -> None:
    evidence_set = _set(_result(result={"similarity": None}))
    assert _evaluate(_cond("similarity", ">=", 0.5), evidence_set) is TruthValue.INDETERMINATE


def test_incomparable_operands_are_indeterminate_never_false() -> None:
    """A string status ordered against a float is a policy-authoring error.
    It must not silently evaluate False, because `Not` would then make it
    True."""
    evidence_set = _set(_result(status=EvidenceResultStatus.PASS))
    assert _evaluate(_cond("status", ">=", 0.5), evidence_set) is TruthValue.INDETERMINATE
    assert (
        _evaluate(Not(condition=_cond("status", ">=", 0.5)), evidence_set)
        is TruthValue.INDETERMINATE
    )


def test_boolean_and_numeric_operands_never_coerce() -> None:
    """`True == 1` is true in Python. It must not be true here: presence is
    not the number one."""
    evidence_set = _set(_result())
    present_as_number = EvidenceCondition(
        evidence_type="FACE_MATCH", field="_present", operator="==", expected_value=1
    )
    assert _evaluate(present_as_number, evidence_set) is TruthValue.FALSE


def test_all_of_is_false_when_any_child_is_false_even_with_unknown_siblings() -> None:
    evidence_set = _set(_result(status=EvidenceResultStatus.FAIL))
    condition = AllOf(
        all_of=[
            _cond("status", "==", "FAIL"),
            EvidenceCondition(
                evidence_type="LIVENESS_ASSESSMENT",
                field="status",
                operator="==",
                expected_value="PASS",
            ),
        ]
    )
    # the liveness leaf is INDETERMINATE (absent), the face leaf TRUE
    assert _evaluate(condition, evidence_set) is TruthValue.INDETERMINATE

    # flip the face leaf to a known failure: decisive despite the unknown
    decisive = AllOf(all_of=[_cond("status", "==", "PASS"), condition.all_of[1]])
    assert _evaluate(decisive, evidence_set) is TruthValue.FALSE


def test_any_of_is_true_when_any_child_is_true_even_with_unknown_siblings() -> None:
    evidence_set = _set(_result(status=EvidenceResultStatus.PASS))
    unknown = EvidenceCondition(
        evidence_type="LIVENESS_ASSESSMENT", field="status", operator="==", expected_value="PASS"
    )
    assert _evaluate(AnyOf(any_of=[_cond("status", "==", "PASS"), unknown]), evidence_set) is (
        TruthValue.TRUE
    )
    assert _evaluate(AnyOf(any_of=[_cond("status", "==", "FAIL"), unknown]), evidence_set) is (
        TruthValue.INDETERMINATE
    )


def test_present_is_always_decidable_in_both_directions() -> None:
    assert _evaluate(_cond("_present", "==", True), _set(_result())) is TruthValue.TRUE
    assert _evaluate(_cond("_present", "==", True), _set()) is TruthValue.FALSE
    assert _evaluate(_cond("_present", "==", False), _set()) is TruthValue.TRUE


def test_present_sees_prohibited_evidence_that_by_type_deliberately_excludes() -> None:
    """Prohibited evidence is never an eligible decision input, so it is not
    in `by_type` -- but its presence is observable, and `_present` is the one
    channel through which a policy may react to it."""
    evidence_set = _set(prohibited=frozenset({"FACE_MATCH"}))
    assert _evaluate(_cond("_present", "==", True), evidence_set) is TruthValue.TRUE
    # every other field remains unobservable
    assert _evaluate(_cond("score", ">=", 0.1), evidence_set) is TruthValue.INDETERMINATE


def test_threshold_ref_resolves_to_its_definition_value() -> None:
    evidence_set = _set(_result(score=0.8))
    thresholds = {
        "face_match_min": ThresholdDefinition(
            name="face_match_min",
            value=0.75,
            model_id="face-v1",
            model_version="1.0.0",
            calibration_reference="cal-1",
            applicable_evidence_type="FACE_MATCH",
        )
    }
    condition = _cond("score", ">=", ThresholdRef(name="face_match_min"))
    assert _evaluate(condition, evidence_set, thresholds) is TruthValue.TRUE

    thresholds["face_match_min"] = thresholds["face_match_min"].model_copy(update={"value": 0.95})
    assert _evaluate(condition, evidence_set, thresholds) is TruthValue.FALSE


def test_unresolvable_threshold_ref_is_indeterminate_not_a_crash() -> None:
    """Policy validation makes this unreachable, so reaching it means the
    policy is internally inconsistent. The engine still must not fail open,
    and must not raise out of a pure function."""
    evidence_set = _set(_result(score=0.8))
    condition = _cond("score", ">=", ThresholdRef(name="never_defined"))
    assert _evaluate(condition, evidence_set, {}) is TruthValue.INDETERMINATE


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        (">=", TruthValue.TRUE),
        (">", TruthValue.FALSE),
        ("<=", TruthValue.TRUE),
        ("<", TruthValue.FALSE),
    ],
)
def test_threshold_boundary_follows_the_authors_operator_choice(operator, expected) -> None:
    """0.55 against 0.55 is not an engine ambiguity -- it is whichever
    comparison the policy author wrote."""
    evidence_set = _set(_result(score=0.55))
    assert _evaluate(_cond("score", operator, 0.55), evidence_set) is expected
