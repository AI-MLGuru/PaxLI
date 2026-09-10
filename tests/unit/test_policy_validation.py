import pytest

from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.condition import AllOf, EvidenceCondition
from core.policy.exceptions import InvalidPolicyError
from core.policy.validation import (
    MAX_CONDITION_NODES,
    validate_condition_complexity,
    validate_condition_semantics,
    validate_envelopes,
    validate_policy_content,
)

_real_catalog = EvidenceResultSchemaCatalog()


def test_condition_referencing_a_real_foundation_008_field_is_valid() -> None:
    """Cross-foundation proof: a condition naming a genuine
    EvidenceResultType/field pair from Foundation-008 passes semantic
    validation without core.policy importing evidence_result internals
    directly."""
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
    )
    validate_condition_semantics(condition, _real_catalog)  # must not raise


def test_condition_referencing_unknown_evidence_type_is_rejected() -> None:
    condition = EvidenceCondition(
        evidence_type="NOT_A_REAL_TYPE", field="whatever", operator="==", expected_value=True
    )
    with pytest.raises(InvalidPolicyError):
        validate_condition_semantics(condition, _real_catalog)


def test_condition_referencing_unknown_field_on_a_real_type_is_rejected() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="not_a_real_field", operator="==", expected_value=True
    )
    with pytest.raises(InvalidPolicyError):
        validate_condition_semantics(condition, _real_catalog)


def test_condition_referencing_universal_status_field_is_valid() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="status", operator="==", expected_value="PASS"
    )
    validate_condition_semantics(condition, _real_catalog)  # must not raise


def test_complexity_bound_rejects_an_oversized_tree() -> None:
    leaf = EvidenceCondition(
        evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
    )
    oversized = AllOf(all_of=[leaf] * (MAX_CONDITION_NODES + 1))
    with pytest.raises(InvalidPolicyError):
        validate_condition_complexity(oversized)


def test_complexity_bound_accepts_a_reasonably_sized_tree() -> None:
    leaf = EvidenceCondition(
        evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
    )
    reasonable = AllOf(all_of=[leaf, leaf, leaf])
    validate_condition_complexity(reasonable)  # must not raise


@pytest.mark.parametrize("forbidden_key", ["code", "eval", "exec", "script", "__import__"])
def test_gate_envelope_rejects_executable_shaped_keys(forbidden_key: str) -> None:
    with pytest.raises(InvalidPolicyError):
        validate_envelopes(gates=({forbidden_key: "print(1)"},), rules=(), conflict_resolution=None)


def test_gate_envelope_accepts_ordinary_data_only_shapes() -> None:
    validate_envelopes(
        gates=({"id": "gate-1", "outcome": "REVIEW_REQUIRED"},),
        rules=({"id": "rule-1", "weight": 0.5},),
        conflict_resolution={"strategy": "most_restrictive"},
    )  # must not raise


def test_validate_policy_content_runs_the_full_pipeline() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
    )
    validate_policy_content(
        conditions=condition,
        gates=(),
        rules=(),
        thresholds={"pass": 0.9},
        conflict_resolution=None,
        catalog=_real_catalog,
    )  # must not raise
