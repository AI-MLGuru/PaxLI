class InvalidEvidenceResultError(ValueError):
    """Raised when an evidence result submission violates its schema or
    semantic contract (EVD-3.24). Rejected before persistence, never
    silently corrected into a safe status -- the caller (a future
    processing component) decides how to recover, e.g. by submitting a
    separate INCONCLUSIVE result with reason_codes=["EVIDENCE_SCHEMA_INVALID"].
    """
