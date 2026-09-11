from enum import StrEnum


class VerificationStatus(StrEnum):
    """Part IV §4.4/§4.5's normative lifecycle -- WF-001 §1. Deliberately
    disjoint from core.decision.enums.DecisionOutcome: WF-4.1.4 forbids
    VERIFIED/REJECTED as lifecycle values, and §4.4 forbids REVIEW_REQUIRED/
    INCONCLUSIVE the same way -- both are decision outcomes attached to a
    COMPLETED session, never lifecycle states themselves. See
    docs/decisions/WF-001-verification-workflow-semantics.md §1 for the
    reconciliation that corrected this from an earlier, nonconformant
    eight-value enum that used the four decision outcomes as lifecycle
    values directly."""

    CREATED = "CREATED"
    CAPTURING = "CAPTURING"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


VALID_STATUS_TRANSITIONS: dict[VerificationStatus, frozenset[VerificationStatus]] = {
    VerificationStatus.CREATED: frozenset(
        {
            VerificationStatus.CAPTURING,
            VerificationStatus.SUBMITTED,
            VerificationStatus.EXPIRED,
            VerificationStatus.CANCELLED,
        }
    ),
    VerificationStatus.CAPTURING: frozenset(
        {
            VerificationStatus.SUBMITTED,
            VerificationStatus.EXPIRED,
            VerificationStatus.CANCELLED,
        }
    ),
    VerificationStatus.SUBMITTED: frozenset(
        {
            VerificationStatus.PROCESSING,
            VerificationStatus.EXPIRED,
            VerificationStatus.CANCELLED,
        }
    ),
    # Deliberately no EXPIRED here (WF-001 §7 / Part IV §4.6): a PROCESSING
    # session past its deadline is never transitioned to EXPIRED directly.
    # It is resolved by running the Decision Engine with
    # EvaluationReason.EXPIRATION and landing at COMPLETED with an
    # INCONCLUSIVE decision instead -- a session that reached PROCESSING
    # always ends up with a DecisionResult, even when that result is the
    # expiration-forced INCONCLUSIVE.
    VerificationStatus.PROCESSING: frozenset(
        {
            VerificationStatus.COMPLETED,
            VerificationStatus.CANCELLED,
        }
    ),
    VerificationStatus.COMPLETED: frozenset(),
    VerificationStatus.EXPIRED: frozenset(),
    VerificationStatus.CANCELLED: frozenset(),
}

# WF-001 §1: a status is terminal iff nothing may transition out of it --
# derived, never hand-duplicated, so this and VALID_STATUS_TRANSITIONS can
# never silently drift apart. Three values now (COMPLETED, EXPIRED,
# CANCELLED), not the six a pre-WF-001 version of this constant produced.
TERMINAL_STATUSES: frozenset[VerificationStatus] = frozenset(
    status for status, transitions in VALID_STATUS_TRANSITIONS.items() if not transitions
)

# WF-001 §8 / Part IV §4.8.4, §4.19.2: ordinary evidence submission is
# legal only while the session is still collecting input. This is an
# allow-list, not a deny-list of terminals -- SUBMITTED and PROCESSING must
# also reject submission despite neither being terminal (the client already
# signaled "done"), and an allow-list fails safe automatically against any
# future new status without needing to remember to add it to a deny-list.
EVIDENCE_SUBMISSION_ALLOWED_STATUSES: frozenset[VerificationStatus] = frozenset(
    {VerificationStatus.CREATED, VerificationStatus.CAPTURING}
)

# WF-001 §7 / Part IV §4.6: the set VerificationSession.expire_if_needed()
# checks. Deliberately excludes PROCESSING -- a session past its deadline
# while PROCESSING must produce a DecisionResult (an INCONCLUSIVE one, via
# EvaluationReason.EXPIRATION) and land at COMPLETED, never EXPIRED
# directly. That case is the workflow orchestration boundary's job
# (WF-004), not this lazy check, which only ever covers "no decision was
# ever attempted."
PRE_PROCESSING_STATUSES: frozenset[VerificationStatus] = frozenset(
    {VerificationStatus.CREATED, VerificationStatus.CAPTURING, VerificationStatus.SUBMITTED}
)


class AssuranceLevel(StrEnum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    ENHANCED = "ENHANCED"
