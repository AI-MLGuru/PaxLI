class SessionNotFoundError(Exception):
    pass


class SessionExpiredError(Exception):
    """Raised when an operation that requires an actively-collecting
    session (evidence submission -- core.evidence.service.EvidenceService.add())
    is attempted against a session outside {CREATED, CAPTURING}
    (WF-001 §8). The name predates WF-001 and is kept for that one call
    site rather than renamed -- DE-004 Phase 4 already established this
    exception as the generic "session is not accepting this operation"
    signal, and the API's error message ("Verification session is not
    active") was already accurate for every status, not merely EXPIRED."""


class SessionAlreadyTerminalError(Exception):
    """Raised by cancel() (WF-001 §6) when the session has already
    reached COMPLETED, EXPIRED, or CANCELLED -- a single, general
    exception for all three, never a bare ValueError escaping from
    VerificationSession.transition_to()'s own internal legality check.
    Distinct from SessionExpiredError: this covers an explicit, client-
    intent-driven operation (cancellation) finding the session already
    terminal, not the evidence-submission allow-list."""


class ConcurrentTransitionError(Exception):
    """Raised when a lifecycle transition's compare-and-swap write
    (WF-001 §11) affects zero rows -- the session's status already
    changed since the caller last read it (or the session does not
    exist for this tenant). The database is the final arbiter on this
    race, never an application-level check-then-write -- same
    discipline as PolicyActivationConflictError/DeletionAlreadyRequestedError,
    both translations of a real database-level conflict, never a
    substitute for one via check-then-write."""
