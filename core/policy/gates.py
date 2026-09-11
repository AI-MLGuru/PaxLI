"""DE-003 §4: the Gate schema, formalizing DEC-5.18. Replaces the previous
`gates: tuple[dict[str, Any], ...]` opaque envelope.

`kind` is the mechanism that makes DEC-5.22's conflict semantics
mechanically distinguishable from ordinary blocking without a separate
`conflict_resolution` construct (DE-002/DE-003 §9): a CONFLICT-kind gate is
a policy author's explicit recognition that a particular evidence
combination is contradictory, not an engine-invented heuristic.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from core.decision.enums import DecisionOutcome, EngineReasonCode
from core.policy.condition import Condition
from core.policy.reason_codes import is_valid_policy_reason_code

GateFailureOutcome = Literal[
    DecisionOutcome.REJECTED, DecisionOutcome.REVIEW_REQUIRED, DecisionOutcome.INCONCLUSIVE
]


class GateKind(StrEnum):
    BLOCKING = "BLOCKING"
    CONFLICT = "CONFLICT"


class Gate(BaseModel):
    """DE-003 Amendment A: `failure_reason_code` is REQUIRED for a
    BLOCKING gate (there is no generic fallback code it could silently
    receive) and OPTIONAL for a CONFLICT gate, where omission defaults to
    `ENGINE:UNRESOLVED_EVIDENCE_CONFLICT` -- enforced here, not left to
    evaluator-time interpretation, so an invalid gate is rejected at policy
    activation (DEC-5.9.1) rather than producing an ambiguous decision.

    `extra="forbid"`: SEC-7.23.8 forbids arbitrary executable-shaped
    content in policy structures. The previous dict-based envelope
    enforced this with an explicit forbidden-key scan; a fixed Pydantic
    schema enforces the same guarantee structurally, but only if unknown
    fields are rejected rather than silently ignored (Pydantic's default)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: GateKind
    condition: Condition
    priority: int
    on_failure_outcome: GateFailureOutcome
    failure_reason_code: str | None = None

    @model_validator(mode="after")
    def _reason_code_matches_kind(self) -> "Gate":
        if self.kind == GateKind.BLOCKING and self.failure_reason_code is None:
            raise ValueError("failure_reason_code is required for a BLOCKING gate")
        if self.failure_reason_code is not None and not is_valid_policy_reason_code(
            self.failure_reason_code
        ):
            raise ValueError(
                f"failure_reason_code {self.failure_reason_code!r} is not a valid "
                "POLICY: reason code"
            )
        return self

    def resolved_reason_code(self) -> str:
        """The code actually attached to the decision when this gate fires
        -- the explicit code if set, else the CONFLICT default. Never
        called for a BLOCKING gate with no code: the validator above makes
        that state unconstructable."""
        if self.failure_reason_code is not None:
            return self.failure_reason_code
        return EngineReasonCode.UNRESOLVED_EVIDENCE_CONFLICT.value
