from enum import StrEnum


class DecisionOutcome(StrEnum):
    """Part V §5.3's closed outcome set. Deliberately its own type, not
    core.verification.enums.VerificationStatus: Part IV/CLAUDE.md's
    constitutional state-separation rule ("Session lifecycle state !=
    Processing execution state != Evidence status != Final verification
    decision") means a decision outcome and a session lifecycle state must
    never be representable by the same type, even though their string
    values overlap for the four shared labels."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCONCLUSIVE = "INCONCLUSIVE"


class EngineReasonCode(StrEnum):
    """DE-003 §8: the closed, engine-controlled reason-code namespace.
    Never policy-authored -- see core.policy.reason_codes for the POLICY:
    namespace. POLICY_NOT_FOUND is deliberately absent: under early policy
    binding (DE-002/DE-003 §1) that failure can only occur at session
    creation, before any session/decision exists, so it is a session-
    creation API error, never a member of Decision.reason_codes."""

    DECISION_ENGINE_ERROR = "ENGINE:DECISION_ENGINE_ERROR"
    POLICY_INVALID = "ENGINE:POLICY_INVALID"
    POLICY_VERSION_UNAVAILABLE = "ENGINE:POLICY_VERSION_UNAVAILABLE"
    REQUIRED_EVIDENCE_MISSING = "ENGINE:REQUIRED_EVIDENCE_MISSING"
    EVIDENCE_SCHEMA_INVALID = "ENGINE:EVIDENCE_SCHEMA_INVALID"
    DECISION_TIMEOUT = "ENGINE:DECISION_TIMEOUT"
    SESSION_EXPIRED_DURING_PROCESSING = "ENGINE:SESSION_EXPIRED_DURING_PROCESSING"
    CALIBRATION_MODEL_MISMATCH = "ENGINE:CALIBRATION_MODEL_MISMATCH"
    NO_MATCHING_RULE = "ENGINE:NO_MATCHING_RULE"
    UNRESOLVED_EVIDENCE_CONFLICT = "ENGINE:UNRESOLVED_EVIDENCE_CONFLICT"
