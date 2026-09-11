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
