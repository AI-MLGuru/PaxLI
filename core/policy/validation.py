"""DEC-5.9/5.10 validation pipeline: schema -> semantic -> complexity.

Establishes "this policy is structurally valid and safe to store" -- never
"this policy produces a decision" (Foundation-009 discovery). Nothing here
executes a condition, gate, or rule; validation only inspects shape.
"""

from typing import Any

from core.policy.condition import (
    Condition,
    condition_depth,
    condition_node_count,
    iter_evidence_conditions,
)
from core.policy.exceptions import InvalidPolicyError
from core.policy.schema_catalog import EvidenceSchemaCatalog

# Initial, defensible complexity bounds (DEC-5.26) -- not yet security-reviewed
# against a real adversarial-policy corpus; revisit alongside the Decision
# Engine when real policy sizes are known.
MAX_CONDITION_NODES = 64
MAX_CONDITION_DEPTH = 8
MAX_GATES = 32
MAX_RULES = 64

# A loosely-typed gate/rule/conflict_resolution envelope must never carry an
# executable-code-shaped key -- this is the concrete guard against the
# envelope becoming a backdoor for arbitrary executable policy code
# (SEC-7.23.8, explicitly forbidden per Foundation-009 discovery).
_FORBIDDEN_ENVELOPE_KEYS = frozenset({"code", "eval", "exec", "script", "__import__"})


def _reject_executable_shaped_content(label: str, value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_ENVELOPE_KEYS:
                raise InvalidPolicyError(
                    f"{label} contains a forbidden executable-shaped key: {key!r}"
                )
            _reject_executable_shaped_content(label, nested)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_executable_shaped_content(label, item)


def validate_condition_semantics(
    conditions: Condition | None, catalog: EvidenceSchemaCatalog
) -> None:
    """Every EvidenceCondition leaf must reference a real evidence type and
    a real field on that type (DEC-5.14.1/5.14.2) -- checked against the
    injected catalog, never against core.evidence_result internals
    directly."""
    if conditions is None:
        return
    for leaf in iter_evidence_conditions(conditions):
        if not catalog.is_known_evidence_type(leaf.evidence_type):
            raise InvalidPolicyError(f"unknown evidence_type in condition: {leaf.evidence_type!r}")
        if not catalog.supports_field(leaf.evidence_type, leaf.field):
            raise InvalidPolicyError(
                f"evidence_type {leaf.evidence_type!r} has no field {leaf.field!r}"
            )


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


def validate_envelopes(
    *,
    gates: tuple[dict[str, Any], ...],
    rules: tuple[dict[str, Any], ...],
    conflict_resolution: dict[str, Any] | None,
) -> None:
    """Structural validation of the loosely-typed v1 envelopes (Foundation-009
    discovery decision #4): bounded counts, dict-shaped entries, and no
    executable-shaped content. Never validates that a gate/rule is
    semantically correct -- that is the future Decision Engine's schema."""
    if len(gates) > MAX_GATES:
        raise InvalidPolicyError(f"{len(gates)} gates exceeds the {MAX_GATES} bound")
    if len(rules) > MAX_RULES:
        raise InvalidPolicyError(f"{len(rules)} rules exceeds the {MAX_RULES} bound")
    for gate in gates:
        if not isinstance(gate, dict):
            raise InvalidPolicyError("each gate must be an object")
        _reject_executable_shaped_content("gate", gate)
    for rule in rules:
        if not isinstance(rule, dict):
            raise InvalidPolicyError("each rule must be an object")
        _reject_executable_shaped_content("rule", rule)
    if conflict_resolution is not None:
        _reject_executable_shaped_content("conflict_resolution", conflict_resolution)


def validate_policy_content(
    *,
    conditions: Condition | None,
    gates: tuple[dict[str, Any], ...],
    rules: tuple[dict[str, Any], ...],
    thresholds: dict[str, float],
    conflict_resolution: dict[str, Any] | None,
    catalog: EvidenceSchemaCatalog,
) -> None:
    """Full DEC-5.9/5.10 pipeline entry point. Schema-shape validation
    happens implicitly via Pydantic construction of VerificationPolicy
    before this runs; this covers the semantic and complexity stages that
    Pydantic alone cannot express."""
    validate_condition_semantics(conditions, catalog)
    validate_condition_complexity(conditions)
    validate_envelopes(gates=gates, rules=rules, conflict_resolution=conflict_resolution)
    for key, value in thresholds.items():
        if not isinstance(key, str) or not isinstance(value, int | float):
            raise InvalidPolicyError("thresholds must map string names to numeric values")
