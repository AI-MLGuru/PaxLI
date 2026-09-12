class EvidenceNotFoundError(Exception):
    """Raised by write-path operations (deletion) that cannot proceed
    without an existing, tenant-scoped evidence row -- unlike list()/get(),
    which return an empty/None result, a deletion request against evidence
    that was never created (or belongs to another tenant) is a genuine
    error, not a no-op (EVD-3.26.2)."""


class EvidenceDeletedError(Exception):
    """Raised by the read path when a tenant-scoped tombstone exists for
    the requested evidence_id -- Invariant-06 remediation Phase 4's firm
    choice: a deleted evidence ID must remain distinguishable from one that
    never existed (410 Gone), never collapsed into an ordinary 404. Raised
    regardless of whether the tombstone has executed_at set: once deletion
    has been durably requested, the resource must stop being served as
    live even if reconciliation hasn't physically caught up yet."""


class IdempotencyKeyConflictError(Exception):
    """Raised by the repository (WF-001 §10/§11-adjacent) when a concurrent
    INSERT already claimed this (tenant_id, session_id, idempotency_key)
    between this call's own upfront get_by_idempotency_key() check and its
    INSERT attempt -- a translation of the table's UNIQUE constraint, same
    discipline as core.verification.exceptions.IdempotencyKeyConflictError
    and DecisionAlreadyExistsError. EvidenceService.add() catches this and
    re-fetches the winning row, then applies the same fingerprint
    comparison as the upfront check."""


class IdempotencyKeyReusedError(Exception):
    """Raised when an `Idempotency-Key` is replayed against an evidence
    submission whose canonical fingerprint (WF-001 §10 / WF-4.9.3) does not
    match the fingerprint stored on the original write -- materially
    different reuse of the same key (a different evidence_type, or
    different file content entirely), mapped to `409 IDEMPOTENCY_KEY_REUSED`.
    Distinct from IdempotencyKeyConflictError: that one is the database's
    mechanical "someone else's INSERT already claimed this key" signal;
    this one is the service's semantic verdict, reached only after
    comparing fingerprints."""
