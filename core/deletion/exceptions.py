class DeletionAlreadyRequestedError(RuntimeError):
    """Raised when a deletion request races another one for the same
    resource and loses -- a translation of the tombstone table's primary
    key violation, never a substitute for it via an application-level
    check-then-insert (same shape as PolicyActivationConflictError,
    Foundation-009 discovery question 8). The losing caller's session is
    left in an aborted-transaction state, exactly like the policy
    conflict case; a fresh retry naturally resolves to the idempotent
    already-requested tombstone."""


class TombstoneNotFoundError(LookupError):
    """Raised by a narrow tombstone-transition repository method (e.g.
    mark_tombstone_executed) when no tenant-scoped tombstone row matches.
    This is a defensive check, not an expected runtime path -- correct
    service usage always confirms the tombstone exists (via get_tombstone
    or the request transaction that created it) before transitioning it."""


class InvalidDeletionRequestError(ValueError):
    """Raised before anything is persisted -- no basis, no authorization
    context, no deletion (EVD-3.26.2/3.26.3). Same discipline as
    InvalidPolicyError/InvalidEvidenceResultError: rejected at the domain
    boundary, never partially recorded."""
