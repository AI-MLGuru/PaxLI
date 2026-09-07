from dataclasses import dataclass
from enum import StrEnum

from core.verification.enums import VerificationStatus


class EvidenceDecision(StrEnum):
    VERIFIED = VerificationStatus.VERIFIED
    REJECTED = VerificationStatus.REJECTED
    REVIEW_REQUIRED = VerificationStatus.REVIEW_REQUIRED
    INCONCLUSIVE = VerificationStatus.INCONCLUSIVE


@dataclass(frozen=True)
class DecisionInput:
    biometric_score: float | None = None
    liveness_score: float | None = None
    document_valid: bool | None = None
    identity_consistent: bool | None = None


@dataclass(frozen=True)
class Decision:
    status: EvidenceDecision
    reason_codes: tuple[str, ...]


class DecisionEngine:
    """Policy boundary. Thresholds belong to calibrated policy/model configuration."""

    def evaluate(self, evidence: DecisionInput) -> Decision:
        if evidence.biometric_score is None or evidence.liveness_score is None:
            return Decision(EvidenceDecision.INCONCLUSIVE, ("INSUFFICIENT_EVIDENCE",))
        return Decision(EvidenceDecision.REVIEW_REQUIRED, ("POLICY_NOT_CONFIGURED",))
