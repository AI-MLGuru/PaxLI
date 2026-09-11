"""DE-003 §5: the Rule schema, formalizing DEC-5.19. Replaces the previous
`rules: tuple[dict[str, Any], ...]` opaque envelope. Evaluation order is
ascending priority, first match wins -- deterministic without depending on
declaration/iteration order (DEC-5.19.1), enforced by requiring globally
unique priorities within a policy (core.policy.validation) rather than
attempting to detect which rules could ever both match.
"""

from pydantic import BaseModel, ConfigDict, model_validator

from core.decision.enums import DecisionOutcome
from core.policy.condition import Condition
from core.policy.reason_codes import is_valid_policy_reason_code


class Rule(BaseModel):
    """`outcome` may be any of the four decision outcomes, including
    INCONCLUSIVE -- a policy explicitly routing a recognized evidence shape
    to INCONCLUSIVE is deliberate authorship (EVD-3.22.4), not engine
    safe-failure, and reason_code is required precisely so that
    distinction stays visible in provenance (DEC-5.28.1).

    `extra="forbid"`: same SEC-7.23.8 rationale as core.policy.gates.Gate."""

    model_config = ConfigDict(extra="forbid")

    id: str
    condition: Condition
    outcome: DecisionOutcome
    priority: int
    reason_code: str

    @model_validator(mode="after")
    def _reason_code_is_valid(self) -> "Rule":
        if not is_valid_policy_reason_code(self.reason_code):
            raise ValueError(f"reason_code {self.reason_code!r} is not a valid POLICY: reason code")
        return self
