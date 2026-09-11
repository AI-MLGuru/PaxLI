class InvalidDeletionRequestError(ValueError):
    """Raised before anything is persisted -- no basis, no authorization
    context, no deletion (EVD-3.26.2/3.26.3). Same discipline as
    InvalidPolicyError/InvalidEvidenceResultError: rejected at the domain
    boundary, never partially recorded."""
