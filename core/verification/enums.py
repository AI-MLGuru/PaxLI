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

# DE-003 §13 / DE-004 Phase 4: a status is terminal iff nothing may
# transition out of it -- derived from VALID_STATUS_TRANSITIONS rather than
# listed again by hand, so the two can never silently drift apart. This is
# the exact six-state set WF-4.19.2 requires evidence-submission rejection
# for: VERIFIED, REJECTED, REVIEW_REQUIRED, INCONCLUSIVE, EXPIRED, CANCELLED.
TERMINAL_STATUSES: frozenset[VerificationStatus] = frozenset(
    status for status, transitions in VALID_STATUS_TRANSITIONS.items() if not transitions
)


class AssuranceLevel(StrEnum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    ENHANCED = "ENHANCED"
