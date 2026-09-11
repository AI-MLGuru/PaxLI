import pytest

from core.decision.enums import DecisionOutcome
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.condition import AllOf, EvidenceCondition, ThresholdRef
from core.policy.exceptions import InvalidPolicyError
from core.policy.gates import Gate, GateKind
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.thresholds import ThresholdDefinition
from core.policy.validation import (
    MAX_CONDITION_NODES,
    validate_condition_complexity,
    validate_condition_semantics,
    validate_evidence_requirements,
    validate_gates,
    validate_policy_content,
    validate_rules,
    validate_thresholds,
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


def test_validate_policy_content_runs_the_full_pipeline() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
    )
    validate_policy_content(
        evidence_requirements=(),
        conditions=condition,
        gates=(),
        rules=(),
        thresholds=(),
        catalog=_real_catalog,
    )  # must not raise


def test_duplicate_gate_ids_are_rejected() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="status", operator="==", expected_value="FAIL"
    )
    gate = Gate(
        id="dup",
        kind=GateKind.BLOCKING,
        condition=condition,
        priority=1,
        on_failure_outcome=DecisionOutcome.REJECTED,
        failure_reason_code="POLICY:FACE_MATCH_FAILED",
    )
    duplicate = gate.model_copy(update={"priority": 2})
    with pytest.raises(InvalidPolicyError):
        validate_gates((gate, duplicate))


def test_duplicate_gate_priorities_are_rejected() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="status", operator="==", expected_value="FAIL"
    )
    gate_a = Gate(
        id="a",
        kind=GateKind.BLOCKING,
        condition=condition,
        priority=1,
        on_failure_outcome=DecisionOutcome.REJECTED,
        failure_reason_code="POLICY:GATE_A_FAILED",
    )
    gate_b = gate_a.model_copy(update={"id": "b"})
    with pytest.raises(InvalidPolicyError):
        validate_gates((gate_a, gate_b))


def test_duplicate_rule_priorities_are_rejected() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH", field="status", operator="==", expected_value="PASS"
    )
    rule_a = Rule(
        id="a", condition=condition, outcome=DecisionOutcome.VERIFIED, priority=1,
        reason_code="POLICY:VERIFIED_A",
    )
    rule_b = rule_a.model_copy(update={"id": "b"})
    with pytest.raises(InvalidPolicyError):
        validate_rules((rule_a, rule_b))


def test_duplicate_threshold_names_are_rejected() -> None:
    threshold = ThresholdDefinition(
        name="dup", value=0.5, model_id="m", model_version="v1",
        calibration_reference="c1", applicable_evidence_type="FACE_MATCH",
    )
    with pytest.raises(InvalidPolicyError):
        validate_thresholds((threshold, threshold.model_copy()))


def test_duplicate_evidence_requirement_types_are_rejected() -> None:
    requirement = EvidenceRequirement(
        evidence_type="FACE_MATCH", level=EvidenceRequirementLevel.REQUIRED
    )
    with pytest.raises(InvalidPolicyError):
        validate_evidence_requirements(
            (requirement, requirement.model_copy()), catalog=_real_catalog
        )


def test_prohibited_evidence_type_rejects_non_present_field_reference() -> None:
    """DE-003 §3/§9: PROHIBITED evidence's only legal condition field is
    _present -- referencing any other field must fail policy validation."""
    prohibited = EvidenceRequirement(
        evidence_type="EXTERNAL_IDENTITY_PROVIDER", level=EvidenceRequirementLevel.PROHIBITED
    )
    condition = EvidenceCondition(
        evidence_type="EXTERNAL_IDENTITY_PROVIDER",
        field="matched",
        operator="==",
        expected_value=True,
    )
    with pytest.raises(InvalidPolicyError):
        validate_policy_content(
            evidence_requirements=(prohibited,),
            conditions=condition,
            gates=(),
            rules=(),
            thresholds=(),
            catalog=_real_catalog,
        )


def test_prohibited_evidence_type_accepts_present_field_reference() -> None:
    prohibited = EvidenceRequirement(
        evidence_type="EXTERNAL_IDENTITY_PROVIDER", level=EvidenceRequirementLevel.PROHIBITED
    )
    condition = EvidenceCondition(
        evidence_type="EXTERNAL_IDENTITY_PROVIDER",
        field="_present",
        operator="==",
        expected_value=True,
    )
    validate_policy_content(
        evidence_requirements=(prohibited,),
        conditions=condition,
        gates=(),
        rules=(),
        thresholds=(),
        catalog=_real_catalog,
    )  # must not raise


def test_threshold_ref_cross_checked_against_definitions() -> None:
    threshold = ThresholdDefinition(
        name="face_match_pass", value=0.55, model_id="insightface", model_version="v1",
        calibration_reference="cal-1", applicable_evidence_type="FACE_MATCH",
    )
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH",
        field="similarity",
        operator=">=",
        expected_value=ThresholdRef(name="face_match_pass"),
    )
    validate_policy_content(
        evidence_requirements=(),
        conditions=condition,
        gates=(),
        rules=(),
        thresholds=(threshold,),
        catalog=_real_catalog,
    )  # must not raise


def test_threshold_ref_to_unknown_threshold_is_rejected() -> None:
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH",
        field="similarity",
        operator=">=",
        expected_value=ThresholdRef(name="does_not_exist"),
    )
    with pytest.raises(InvalidPolicyError):
        validate_policy_content(
            evidence_requirements=(),
            conditions=condition,
            gates=(),
            rules=(),
            thresholds=(),
            catalog=_real_catalog,
        )


def test_threshold_ref_to_mismatched_evidence_type_is_rejected() -> None:
    threshold = ThresholdDefinition(
        name="doc_quality", value=0.5, model_id="m", model_version="v1",
        calibration_reference="c1", applicable_evidence_type="DOCUMENT_QUALITY",
    )
    condition = EvidenceCondition(
        evidence_type="FACE_MATCH",
        field="similarity",
        operator=">=",
        expected_value=ThresholdRef(name="doc_quality"),
    )
    with pytest.raises(InvalidPolicyError):
        validate_policy_content(
            evidence_requirements=(),
            conditions=condition,
            gates=(),
            rules=(),
            thresholds=(threshold,),
            catalog=_real_catalog,
        )
