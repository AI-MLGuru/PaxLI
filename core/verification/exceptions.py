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


class IdempotencyKeyConflictError(Exception):
    """Raised by the repository (WF-001 §10/§11-adjacent) when a concurrent
    INSERT already claimed this (tenant_id, idempotency_key) between this
    call's own upfront get_by_idempotency_key() check and its INSERT
    attempt -- a translation of the table's UNIQUE constraint, same
    discipline as DecisionAlreadyExistsError/PolicyActivationConflictError.
    Purely mechanical: it says nothing about whether the two competing
    requests agree on WHAT they were creating. VerificationSessionService.
    create() catches this and re-fetches the winning row, then applies the
    same fingerprint comparison as the upfront check -- convergence and
    reuse-rejection must behave identically regardless of which of the two
    racing requests happened to win the INSERT."""


class IdempotencyKeyReusedError(Exception):
    """Raised when an `Idempotency-Key` is replayed against a request whose
    canonical fingerprint (WF-001 §10 / WF-4.9.3) does not match the
    fingerprint stored on the original write -- materially different reuse
    of the same key, mapped to `409 IDEMPOTENCY_KEY_REUSED`. Distinct from
    IdempotencyKeyConflictError: that one is the database's mechanical
    "someone else's INSERT already claimed this key" signal; this one is
    the service's semantic verdict, reached only after comparing the
    recomputed fingerprint of the new request against the stored
    fingerprint of whichever row -- the caller's own successful insert's
    predecessor, or the winner of a concurrent race -- actually exists."""
