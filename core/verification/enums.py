from enum import StrEnum


class VerificationStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCONCLUSIVE = "INCONCLUSIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


VALID_STATUS_TRANSITIONS: dict[VerificationStatus, frozenset[VerificationStatus]] = {
    VerificationStatus.CREATED: frozenset(
        {
            VerificationStatus.PROCESSING,
            VerificationStatus.EXPIRED,
            VerificationStatus.CANCELLED,
        }
    ),
    VerificationStatus.PROCESSING: frozenset(
        {
            VerificationStatus.VERIFIED,
            VerificationStatus.REJECTED,
            VerificationStatus.REVIEW_REQUIRED,
            VerificationStatus.INCONCLUSIVE,
            VerificationStatus.EXPIRED,
            VerificationStatus.CANCELLED,
        }
    ),
    VerificationStatus.VERIFIED: frozenset(),
    VerificationStatus.REJECTED: frozenset(),
    VerificationStatus.REVIEW_REQUIRED: frozenset(),
    VerificationStatus.INCONCLUSIVE: frozenset(),
    VerificationStatus.EXPIRED: frozenset(),
    VerificationStatus.CANCELLED: frozenset(),
}


class AssuranceLevel(StrEnum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    ENHANCED = "ENHANCED"
