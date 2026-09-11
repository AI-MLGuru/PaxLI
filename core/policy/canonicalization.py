"""Canonical normalization (DEC-5.11) and integrity hashing, reusing
Foundation-008's exact technique (sort_keys=True JSON + SHA-256) rather
than inventing a second scheme.

The hash is computed over policy CONTENT only -- evidence_requirements,
conditions, gates, rules, thresholds, default_outcome, schema_version --
never policy_id, version, tenant_id, status, or any timestamp. This is a
deliberate property: two versions with content-identical bodies (e.g. an
ACTIVE version and a later rollback that reproduces it) hash identically,
which is what makes rollback's provenance proof possible. Two structurally
different bodies always hash differently.

DE-003 extended policy content to typed Gate/Rule/EvidenceRequirement/
ThresholdDefinition collections; `model_dump(mode="json")` on each gives a
deterministic dict representation to feed into the same sort_keys=True
JSON scheme -- no per-field hand-canonicalization needed for these, unlike
the condition tree's commutative AllOf/AnyOf children (below).
"""

import hashlib
import json
from typing import Any

from core.decision.enums import DecisionOutcome
from core.policy.condition import AllOf, AnyOf, Condition, EvidenceCondition, Not
from core.policy.gates import Gate
from core.policy.requirements import EvidenceRequirement
from core.policy.rules import Rule
from core.policy.thresholds import ThresholdDefinition


def _canonicalize_condition(condition: Condition | None) -> dict[str, Any] | None:
    """Recursively normalizes a condition tree so that AllOf/AnyOf children
    order never affects the resulting hash -- those combinators are
    commutative, so [A, B] and [B, A] must be equivalent for hashing
    purposes even though the JSON list order is not `sort_keys`-normalized
    automatically."""
    if condition is None:
        return None
    if isinstance(condition, EvidenceCondition):
        return {
            "type": "evidence_condition",
            "evidence_type": condition.evidence_type,
            "field": condition.field,
            "operator": condition.operator,
            "expected_value": condition.expected_value.model_dump(mode="json")
            if hasattr(condition.expected_value, "model_dump")
            else condition.expected_value,
        }
    if isinstance(condition, AllOf):
        children = [_canonicalize_condition(child) for child in condition.all_of]
        children.sort(key=lambda node: json.dumps(node, sort_keys=True))
        return {"type": "all_of", "all_of": children}
    if isinstance(condition, AnyOf):
        children = [_canonicalize_condition(child) for child in condition.any_of]
        children.sort(key=lambda node: json.dumps(node, sort_keys=True))
        return {"type": "any_of", "any_of": children}
    if isinstance(condition, Not):
        return {"type": "not", "condition": _canonicalize_condition(condition.condition)}
    raise TypeError(f"unknown condition node type: {type(condition)!r}")


def canonicalize_policy_content(
    *,
    schema_version: str,
    evidence_requirements: tuple[EvidenceRequirement, ...],
    conditions: Condition | None,
    gates: tuple[Gate, ...],
    rules: tuple[Rule, ...],
    thresholds: tuple[ThresholdDefinition, ...],
    default_outcome: DecisionOutcome | None,
) -> str:
    """Deterministic JSON string for content-hashing. Not itself the hash --
    callers pass this to compute_canonical_hash, or compare two calls'
    output directly to prove normalization stability in tests."""
    return json.dumps(
        {
            "schema_version": schema_version,
            "evidence_requirements": [
                req.model_dump(mode="json") for req in evidence_requirements
            ],
            "conditions": _canonicalize_condition(conditions),
            "gates": [
                {
                    **gate.model_dump(mode="json"),
                    "condition": _canonicalize_condition(gate.condition),
                }
                for gate in gates
            ],
            "rules": [
                {
                    **rule.model_dump(mode="json"),
                    "condition": _canonicalize_condition(rule.condition),
                }
                for rule in rules
            ],
            "thresholds": [t.model_dump(mode="json") for t in thresholds],
            "default_outcome": default_outcome.value if default_outcome is not None else None,
        },
        sort_keys=True,
        default=str,
    )


def compute_canonical_hash(
    *,
    schema_version: str,
    evidence_requirements: tuple[EvidenceRequirement, ...],
    conditions: Condition | None,
    gates: tuple[Gate, ...],
    rules: tuple[Rule, ...],
    thresholds: tuple[ThresholdDefinition, ...],
    default_outcome: DecisionOutcome | None,
) -> str:
    canonical = canonicalize_policy_content(
        schema_version=schema_version,
        evidence_requirements=evidence_requirements,
        conditions=conditions,
        gates=gates,
        rules=rules,
        thresholds=thresholds,
        default_outcome=default_outcome,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
