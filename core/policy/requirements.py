"""DE-003 §3: the evidence-requirement schema. Replaces the previous
`evidence_requirements: dict[str, Any]` free-form envelope -- DEC-5.5/5.6's
required/optional/prohibited/conditionally-required vocabulary now has an
actual shape, and DEC-5.4.3's "undeclared evidence must not influence the
decision" becomes a filter over this tuple rather than a documented
intention.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from core.policy.condition import Condition


class EvidenceRequirementLevel(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    PROHIBITED = "PROHIBITED"
    CONDITIONALLY_REQUIRED = "CONDITIONALLY_REQUIRED"


class EvidenceRequirement(BaseModel):
    """`condition` is meaningful (and required) only for
    CONDITIONALLY_REQUIRED -- reuses the existing Condition tree rather than
    inventing a second expression language (DE-003 §3)."""

    model_config = ConfigDict(extra="forbid")

    evidence_type: str
    level: EvidenceRequirementLevel
    condition: Condition | None = None

    @model_validator(mode="after")
    def _condition_matches_level(self) -> "EvidenceRequirement":
        if self.level == EvidenceRequirementLevel.CONDITIONALLY_REQUIRED:
            if self.condition is None:
                raise ValueError(
                    "condition is required when level is CONDITIONALLY_REQUIRED"
                )
        elif self.condition is not None:
            raise ValueError(
                f"condition is only meaningful for CONDITIONALLY_REQUIRED, not {self.level.value}"
            )
        return self
