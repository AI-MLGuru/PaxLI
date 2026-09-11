"""DE-003 §6: threshold definitions, referenced by name from
`ThresholdRef` inside a condition (core.policy.condition). Replaces the
previous bare `thresholds: dict[str, float]`, which had no model or
calibration binding at all and could not satisfy DEC-5.20.2/5.21.3
(landmine 3 from DE-002)."""

from pydantic import BaseModel, ConfigDict


class ThresholdDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    model_id: str
    model_version: str
    calibration_reference: str
    applicable_evidence_type: str
