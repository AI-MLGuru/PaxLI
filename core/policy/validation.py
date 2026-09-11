"""DEC-5.9/5.10 validation pipeline: schema -> semantic -> complexity.

Establishes "this policy is structurally valid and safe to store" -- never
"this policy produces a decision" (Foundation-009 discovery). Nothing here
executes a condition, gate, or rule; validation only inspects shape.

DE-003 extends this pipeline to the now-typed Gate/Rule/EvidenceRequirement/
ThresholdDefinition collections: id/priority uniqueness, evidence_type
cross-references, ThresholdRef -> ThresholdDefinition binding, and the
PROHIBITED-level "_present is the only legal field" restriction (DE-003
§2/§3/§9). Reason-code format/collision checks live on Gate/Rule
themselves (core.policy.gates/.rules) since they don't depend on anything
external to the object -- this module owns only cross-object and
catalog-dependent checks.
"""

from core.policy.condition import (
    Condition,
    EvidenceCondition,
    ThresholdRef,
    condition_depth,
    condition_node_count,
    iter_evidence_conditions,
)
from core.policy.exceptions import InvalidPolicyError
from core.policy.gates import Gate
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.schema_catalog import EvidenceSchemaCatalog
from core.policy.thresholds import ThresholdDefinition

# Initial, defensible complexity bounds (DEC-5.26) -- not yet security-reviewed
# against a real adversarial-policy corpus; revisit alongside the Decision
# Engine when real policy sizes are known.
MAX_CONDITION_NODES = 64
MAX_CONDITION_DEPTH = 8
MAX_GATES = 32
MAX_RULES = 64


def validate_condition_complexity(conditions: Condition | None) -> None:
    if conditions is None:
        return
    nodes = condition_node_count(conditions)
    depth = condition_depth(conditions)
    if nodes > MAX_CONDITION_NODES:
        raise InvalidPolicyError(
            f"condition tree has {nodes} nodes, exceeding the {MAX_CONDITION_NODES} bound"
        )
    if depth > MAX_CONDITION_DEPTH:
        raise InvalidPolicyError(
            f"condition tree has depth {depth}, exceeding the {MAX_CONDITION_DEPTH} bound"
        )


def _prohibited_evidence_types(
    evidence_requirements: tuple[EvidenceRequirement, ...],
) -> frozenset[str]:
    return frozenset(
        req.evidence_type
        for req in evidence_requirements
        if req.level == EvidenceRequirementLevel.PROHIBITED
    )


def _validate_evidence_condition_semantics(
    leaf: EvidenceCondition,
    *,
    catalog: EvidenceSchemaCatalog,
    prohibited_types: frozenset[str],
    threshold_names: dict[str, ThresholdDefinition],
) -> None:
    if not catalog.is_known_evidence_type(leaf.evidence_type):
        raise InvalidPolicyError(f"unknown evidence_type in condition: {leaf.evidence_type!r}")
    if leaf.evidence_type in prohibited_types:
        if leaf.field != "_present":
            raise InvalidPolicyError(
                f"evidence_type {leaf.evidence_type!r} is PROHIBITED -- the only legal "
                f"field reference is '_present', not {leaf.field!r}"
            )
    elif not catalog.supports_field(leaf.evidence_type, leaf.field):
        raise InvalidPolicyError(
            f"evidence_type {leaf.evidence_type!r} has no field {leaf.field!r}"
        )
    if isinstance(leaf.expected_value, ThresholdRef):
        definition = threshold_names.get(leaf.expected_value.name)
        if definition is None:
            raise InvalidPolicyError(
                f"condition references unknown threshold {leaf.expected_value.name!r}"
            )
        if definition.applicable_evidence_type != leaf.evidence_type:
            raise InvalidPolicyError(
                f"threshold {definition.name!r} applies to "
                f"{definition.applicable_evidence_type!r}, not {leaf.evidence_type!r}"
            )


def _validate_all_conditions_in(
    conditions: Condition | None,
    *,
    catalog: EvidenceSchemaCatalog,
    prohibited_types: frozenset[str],
    threshold_names: dict[str, ThresholdDefinition],
) -> None:
    if conditions is None:
        return
    for leaf in iter_evidence_conditions(conditions):
        _validate_evidence_condition_semantics(
            leaf,
            catalog=catalog,
            prohibited_types=prohibited_types,
            threshold_names=threshold_names,
        )


def validate_condition_semantics(
    conditions: Condition | None, catalog: EvidenceSchemaCatalog
) -> None:
    """Standalone entry point kept for callers validating a bare condition
    tree with no policy-level context (no prohibited types, no thresholds)
    -- e.g. unit tests exercising the condition model in isolation."""
    _validate_all_conditions_in(
        conditions, catalog=catalog, prohibited_types=frozenset(), threshold_names={}
    )


def validate_evidence_requirements(
    evidence_requirements: tuple[EvidenceRequirement, ...], *, catalog: EvidenceSchemaCatalog
) -> None:
    seen: set[str] = set()
    for requirement in evidence_requirements:
        if requirement.evidence_type in seen:
            raise InvalidPolicyError(
                f"duplicate evidence_requirements entry for {requirement.evidence_type!r}"
            )
        seen.add(requirement.evidence_type)
        if not catalog.is_known_evidence_type(requirement.evidence_type):
            raise InvalidPolicyError(
                f"unknown evidence_type in evidence_requirements: {requirement.evidence_type!r}"
            )


def validate_thresholds(thresholds: tuple[ThresholdDefinition, ...]) -> None:
    seen: set[str] = set()
    for threshold in thresholds:
        if threshold.name in seen:
            raise InvalidPolicyError(f"duplicate threshold name: {threshold.name!r}")
        seen.add(threshold.name)


def validate_gates(gates: tuple[Gate, ...]) -> None:
    if len(gates) > MAX_GATES:
        raise InvalidPolicyError(f"{len(gates)} gates exceeds the {MAX_GATES} bound")
    seen_ids: set[str] = set()
    seen_priorities: set[int] = set()
    for gate in gates:
        if gate.id in seen_ids:
            raise InvalidPolicyError(f"duplicate gate id: {gate.id!r}")
        seen_ids.add(gate.id)
        if gate.priority in seen_priorities:
            raise InvalidPolicyError(f"duplicate gate priority: {gate.priority!r}")
        seen_priorities.add(gate.priority)


def validate_rules(rules: tuple[Rule, ...]) -> None:
    if len(rules) > MAX_RULES:
        raise InvalidPolicyError(f"{len(rules)} rules exceeds the {MAX_RULES} bound")
    seen_ids: set[str] = set()
    seen_priorities: set[int] = set()
    for rule in rules:
        if rule.id in seen_ids:
            raise InvalidPolicyError(f"duplicate rule id: {rule.id!r}")
        seen_ids.add(rule.id)
        if rule.priority in seen_priorities:
            raise InvalidPolicyError(f"duplicate rule priority: {rule.priority!r}")
        seen_priorities.add(rule.priority)


def validate_policy_content(
    *,
    evidence_requirements: tuple[EvidenceRequirement, ...],
    conditions: Condition | None,
    gates: tuple[Gate, ...],
    rules: tuple[Rule, ...],
    thresholds: tuple[ThresholdDefinition, ...],
    catalog: EvidenceSchemaCatalog,
) -> None:
    """Full DEC-5.9/5.10 pipeline entry point. Structural shape validation
    happens implicitly via Pydantic construction of each typed object
    (Gate/Rule/EvidenceRequirement/ThresholdDefinition/VerificationPolicy)
    before this runs; this covers the semantic and complexity stages that
    Pydantic construction alone cannot express -- cross-references between
    conditions, evidence_requirements, and thresholds."""
    validate_evidence_requirements(evidence_requirements, catalog=catalog)
    validate_thresholds(thresholds)
    validate_gates(gates)
    validate_rules(rules)

    prohibited_types = _prohibited_evidence_types(evidence_requirements)
    threshold_names = {t.name: t for t in thresholds}

    _validate_all_conditions_in(
        conditions,
        catalog=catalog,
        prohibited_types=prohibited_types,
        threshold_names=threshold_names,
    )
    validate_condition_complexity(conditions)
    for requirement in evidence_requirements:
        _validate_all_conditions_in(
            requirement.condition,
            catalog=catalog,
            prohibited_types=prohibited_types,
            threshold_names=threshold_names,
        )
        validate_condition_complexity(requirement.condition)
    for gate in gates:
        _validate_all_conditions_in(
            gate.condition,
            catalog=catalog,
            prohibited_types=prohibited_types,
            threshold_names=threshold_names,
        )
        validate_condition_complexity(gate.condition)
    for rule in rules:
        _validate_all_conditions_in(
            rule.condition,
            catalog=catalog,
            prohibited_types=prohibited_types,
            threshold_names=threshold_names,
        )
        validate_condition_complexity(rule.condition)
