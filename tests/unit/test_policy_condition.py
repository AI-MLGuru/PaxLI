import pytest
from pydantic import TypeAdapter, ValidationError

from core.policy.condition import (
    AllOf,
    AnyOf,
    Condition,
    EvidenceCondition,
    Not,
    condition_depth,
    condition_node_count,
    iter_evidence_conditions,
)

_leaf_a = EvidenceCondition(
    evidence_type="FACE_MATCH", field="similarity", operator=">=", expected_value=0.9
)
_leaf_b = EvidenceCondition(
    evidence_type="DOCUMENT_QUALITY", field="quality_score", operator=">=", expected_value=0.8
)


def test_single_leaf_condition_counts_as_one_node_depth_one() -> None:
    assert condition_node_count(_leaf_a) == 1
    assert condition_depth(_leaf_a) == 1


def test_nested_combinators_count_all_nodes_and_max_depth() -> None:
    tree = AllOf(all_of=[_leaf_a, Not(condition=AnyOf(any_of=[_leaf_b]))])
    # nodes: AllOf, leaf_a, Not, AnyOf, leaf_b = 5
    assert condition_node_count(tree) == 5
    # depth: AllOf -> Not -> AnyOf -> leaf_b = 4
    assert condition_depth(tree) == 4


def test_iter_evidence_conditions_flattens_every_leaf() -> None:
    tree = AllOf(all_of=[_leaf_a, AnyOf(any_of=[_leaf_b, Not(condition=_leaf_a)])])
    leaves = iter_evidence_conditions(tree)
    assert len(leaves) == 3
    assert all(isinstance(leaf, EvidenceCondition) for leaf in leaves)


def test_discriminated_union_rejects_unknown_type_tag() -> None:
    adapter: TypeAdapter[Condition] = TypeAdapter(Condition)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "something_else"})


def test_discriminated_union_round_trips_through_json() -> None:
    adapter: TypeAdapter[Condition] = TypeAdapter(Condition)
    tree = AllOf(all_of=[_leaf_a, _leaf_b])
    parsed = adapter.validate_json(adapter.dump_json(tree))
    assert isinstance(parsed, AllOf)
    assert len(parsed.all_of) == 2
