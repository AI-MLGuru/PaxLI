"""Part V §5.13-5.17 declarative condition model.

This is the one piece of policy content Foundation-009 models with full
rigor (Foundation-009 discovery decision #4): a condition tree is pure,
inert data describing what an evidence reference *is*, never how to combine
outcomes into a decision. Nothing here evaluates a condition against real
evidence -- that is the future Decision Engine's exclusive responsibility.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# "_present" is universal like status/score/quality, but with a different
# origin: it isn't a payload field at all, it's whether any effective
# evidence result of this type exists for the session (DE-003 §2/§9). It is
# also the ONLY field legal against a PROHIBITED-level evidence_type
# (core.policy.validation) -- prohibited evidence can be observed, never
# otherwise inspected.
_UNIVERSAL_FIELDS = frozenset({"status", "score", "quality", "_present"})

ConditionOperator = Literal["==", "!=", ">=", "<=", ">", "<"]


class ThresholdRef(BaseModel):
    """References a policy-level ThresholdDefinition by name instead of
    embedding a literal (DE-003 §2/§6, the fix for landmine 3: a bare float
    in a condition has no model/calibration binding and cannot satisfy
    DEC-5.20.2's "must not be silently reused across incompatible models").
    Semantic validation cross-checks the referenced definition's
    applicable_evidence_type against this condition's own evidence_type."""

    type: Literal["threshold_ref"] = "threshold_ref"
    name: str


ConditionOperand = bool | int | float | str | ThresholdRef


class EvidenceCondition(BaseModel):
    """A single leaf reference into an evidence result's status or payload
    field. Semantic validation (core.policy.validation) checks `evidence_type`
    and `field` against an injected EvidenceSchemaCatalog -- this model
    itself only enforces shape, not whether the reference is real."""

    type: Literal["evidence_condition"] = "evidence_condition"
    evidence_type: str
    field: str
    operator: ConditionOperator
    expected_value: ConditionOperand


class AllOf(BaseModel):
    """WF-HV-005: `all_of` MUST be non-empty. Kleene semantics make an
    empty conjunction vacuously TRUE ("all of zero things" holds) --
    mathematically correct, but a Rule with condition=AllOf(all_of=[])
    and outcome=VERIFIED then fires unconditionally, with zero evidence,
    a live path to an invented VERIFIED that DEC-5.23.2/DEC-5.24 forbid.
    Rejected here, at construction, rather than compensated for inside
    the evaluator -- a malformed policy must never be constructible in
    the first place, not merely handled safely if it somehow is."""

    type: Literal["all_of"] = "all_of"
    all_of: list["Condition"] = Field(min_length=1)


class AnyOf(BaseModel):
    """WF-HV-005: `any_of` MUST be non-empty too. An empty disjunction is
    vacuously FALSE (safe -- the condition simply never matches), not a
    VERIFIED-reachable vulnerability the way AllOf([]) is, but it is
    still a semantically malformed policy construct (a combinator with no
    actual conditions) with no legitimate authoring use case, and is
    rejected for the same "invalid policy shapes must not be
    constructible" reason."""

    type: Literal["any_of"] = "any_of"
    any_of: list["Condition"] = Field(min_length=1)


class Not(BaseModel):
    type: Literal["not"] = "not"
    condition: "Condition"


Condition = Annotated[
    EvidenceCondition | AllOf | AnyOf | Not,
    Field(discriminator="type"),
]

AllOf.model_rebuild()
AnyOf.model_rebuild()
Not.model_rebuild()


def condition_node_count(condition: "Condition") -> int:
    """Counts every node in the tree, including the root -- the basis for
    DEC-5.26's complexity bound. A structural count only; never executes or
    interprets the condition."""
    if isinstance(condition, EvidenceCondition):
        return 1
    if isinstance(condition, AllOf):
        return 1 + sum(condition_node_count(child) for child in condition.all_of)
    if isinstance(condition, AnyOf):
        return 1 + sum(condition_node_count(child) for child in condition.any_of)
    if isinstance(condition, Not):
        return 1 + condition_node_count(condition.condition)
    raise TypeError(f"unknown condition node type: {type(condition)!r}")


def condition_depth(condition: "Condition") -> int:
    """Maximum nesting depth, root counted as depth 1 -- the second half of
    DEC-5.26's complexity bound."""
    if isinstance(condition, EvidenceCondition):
        return 1
    if isinstance(condition, AllOf):
        return 1 + max((condition_depth(child) for child in condition.all_of), default=0)
    if isinstance(condition, AnyOf):
        return 1 + max((condition_depth(child) for child in condition.any_of), default=0)
    if isinstance(condition, Not):
        return 1 + condition_depth(condition.condition)
    raise TypeError(f"unknown condition node type: {type(condition)!r}")


def iter_evidence_conditions(condition: "Condition") -> list[EvidenceCondition]:
    """Flattens every EvidenceCondition leaf out of the tree, for semantic
    validation against an EvidenceSchemaCatalog."""
    if isinstance(condition, EvidenceCondition):
        return [condition]
    if isinstance(condition, AllOf):
        return [leaf for child in condition.all_of for leaf in iter_evidence_conditions(child)]
    if isinstance(condition, AnyOf):
        return [leaf for child in condition.any_of for leaf in iter_evidence_conditions(child)]
    if isinstance(condition, Not):
        return iter_evidence_conditions(condition.condition)
    raise TypeError(f"unknown condition node type: {type(condition)!r}")


__all__ = [
    "_UNIVERSAL_FIELDS",
    "AllOf",
    "AnyOf",
    "Condition",
    "ConditionOperand",
    "ConditionOperator",
    "EvidenceCondition",
    "Not",
    "ThresholdRef",
    "condition_depth",
    "condition_node_count",
    "iter_evidence_conditions",
]
