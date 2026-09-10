"""Canonical normalization (DEC-5.11) and integrity hashing (Foundation-009
discovery question 9), reusing Foundation-008's exact technique
(sort_keys=True JSON + SHA-256) rather than inventing a second scheme.

The hash is computed over policy CONTENT only -- evidence_requirements,
conditions, gates, rules, thresholds, conflict_resolution, schema_version --
never policy_id, version, tenant_id, status, or any timestamp. This is a
deliberate property: two versions with content-identical bodies (e.g. an
ACTIVE version and a later rollback that reproduces it) hash identically,
which is what makes rollback's provenance proof possible (Foundation-009
discovery: "Policy v3 content equivalent to v1"). Two structurally
different bodies always hash differently.
"""

import hashlib
import json
from typing import Any

from core.policy.condition import AllOf, AnyOf, Condition, EvidenceCondition, Not


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
            "expected_value": condition.expected_value,
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
    evidence_requirements: dict[str, Any],
    conditions: Condition | None,
    gates: tuple[dict[str, Any], ...],
    rules: tuple[dict[str, Any], ...],
    thresholds: dict[str, float],
    conflict_resolution: dict[str, Any] | None,
) -> str:
    """Deterministic JSON string for content-hashing. Not itself the hash --
    callers pass this to compute_canonical_hash, or compare two calls'
    output directly to prove normalization stability in tests."""
    return json.dumps(
        {
            "schema_version": schema_version,
            "evidence_requirements": evidence_requirements,
            "conditions": _canonicalize_condition(conditions),
            "gates": list(gates),
            "rules": list(rules),
            "thresholds": thresholds,
            "conflict_resolution": conflict_resolution,
        },
        sort_keys=True,
        default=str,
    )


def compute_canonical_hash(
    *,
    schema_version: str,
    evidence_requirements: dict[str, Any],
    conditions: Condition | None,
    gates: tuple[dict[str, Any], ...],
    rules: tuple[dict[str, Any], ...],
    thresholds: dict[str, float],
    conflict_resolution: dict[str, Any] | None,
) -> str:
    canonical = canonicalize_policy_content(
        schema_version=schema_version,
        evidence_requirements=evidence_requirements,
        conditions=conditions,
        gates=gates,
        rules=rules,
        thresholds=thresholds,
        conflict_resolution=conflict_resolution,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
