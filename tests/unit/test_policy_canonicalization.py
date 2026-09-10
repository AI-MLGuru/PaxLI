from core.policy.canonicalization import compute_canonical_hash
from core.policy.condition import AllOf, EvidenceCondition

_leaf_a = EvidenceCondition(
    evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
)
_leaf_b = EvidenceCondition(
    evidence_type="DOCUMENT_QUALITY", field="quality_score", operator=">=", expected_value=0.8
)


def _hash(conditions, thresholds=None):
    return compute_canonical_hash(
        schema_version="1.0",
        evidence_requirements={},
        conditions=conditions,
        gates=(),
        rules=(),
        thresholds=thresholds or {},
        conflict_resolution=None,
    )


def test_reordered_all_of_children_hash_identically() -> None:
    """AllOf is commutative -- [A, B] and [B, A] describe the same policy
    and must produce the same canonical_hash (Foundation-009 discovery:
    equivalent policies must hash identically)."""
    forward = AllOf(all_of=[_leaf_a, _leaf_b])
    reversed_order = AllOf(all_of=[_leaf_b, _leaf_a])
    assert _hash(forward) == _hash(reversed_order)


def test_genuinely_different_conditions_hash_differently() -> None:
    only_a = AllOf(all_of=[_leaf_a])
    only_b = AllOf(all_of=[_leaf_b])
    assert _hash(only_a) != _hash(only_b)


def test_hash_is_deterministic_across_repeated_calls() -> None:
    tree = AllOf(all_of=[_leaf_a, _leaf_b])
    assert _hash(tree) == _hash(tree)


def test_different_thresholds_hash_differently() -> None:
    assert _hash(None, {"pass": 0.9}) != _hash(None, {"pass": 0.5})


def test_no_conditions_is_a_stable_hashable_state() -> None:
    assert _hash(None) == _hash(None)
