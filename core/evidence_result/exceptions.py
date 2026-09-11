class InvalidEvidenceResultError(ValueError):
    """Raised when an evidence result submission violates its schema or
    semantic contract (EVD-3.24). Rejected before persistence, never
    silently corrected into a safe status -- the caller (a future
    processing component) decides how to recover, e.g. by submitting a
    separate INCONCLUSIVE result with reason_codes=["EVIDENCE_SCHEMA_INVALID"].
    """


class EvidenceResultNotFoundError(Exception):
    """Raised by write-path operations (deletion) that cannot proceed
    without an existing, tenant-scoped evidence_result row -- unlike
    get()/list_for_session(), which return an empty/None result, a
    deletion request against a result that was never created (or belongs
    to another tenant) is a genuine error, not a no-op (EVD-3.26.2)."""
