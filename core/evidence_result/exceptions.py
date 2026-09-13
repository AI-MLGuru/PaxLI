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


class InvalidSupersessionError(ValueError):
    """Raised by EvidenceResultService.supersede() when the addressed
    evidence_result_id is not the current effective row for the given
    (tenant_id, session_id, evidence_type) -- e.g. it belongs to a
    different session or evidence_type, is already superseded, or does
    not exist (WF-HV-009 Finding A). Without this check, a caller could
    silently deactivate an unrelated session's effective evidence purely
    by supplying its ID, corrupting the Decision Engine's effective-
    evidence input for a session it has no authority over."""


class EffectiveResultAlreadyExistsError(Exception):
    """Raised by the repository's add() when a concurrent create() for the
    same (tenant_id, session_id, evidence_type) already won the race for
    the partial unique index on is_effective (HV-010): under READ
    COMMITTED, two callers can both see "no existing effective result" and
    both attempt create() before either commits. The database, not
    application logic, is the final arbiter here (same DE-003 §14
    philosophy as DecisionAlreadyExistsError) -- EvidenceResultService.
    create() catches this and converges on whichever attempt actually won,
    rather than letting a raw IntegrityError escape to the caller."""


class InvalidProvenanceReferenceError(ValueError):
    """Raised by EvidenceResultService.create() when a caller-supplied
    `source_reference` or `parent_evidence_result_ids` entry does not
    belong to the SAME (tenant_id, session_id) as the EvidenceResult
    being created (WF-HV-009 Finding B). The DB-level foreign keys behind
    these fields only prove the referenced row exists somewhere -- for
    `source_reference` that's a single-column FK to evidence.id with no
    tenant/session predicate, and `parent_evidence_result_ids` has no FK
    at all (a bare JSON array). Confirmed live: without this check, a
    caller in one tenant could create an EvidenceResult that falsely
    claims derivation from another tenant's raw evidence or processed
    results, fabricating an audit/lineage trail with no signal that it
    is forged."""
