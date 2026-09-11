from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import InvalidDeletionRequestError

MAX_BASIS_REFERENCE_LENGTH = 512


def validate_deletion_request(
    *,
    deletion_basis: DeletionBasis,
    basis_reference: str | None,
    authorized_by: str,
) -> None:
    """EVD-3.26.2/3.26.3: a deletion request without an identified
    authorization context or an applicable basis is invalid, rejected
    before any tombstone or audit event is created.

    OTHER_AUTHORIZED_BASIS is deliberately the least self-explanatory value
    in the vocabulary -- using it without a reference would make the audit
    trail meaningless, so it is the one value that requires one.
    """
    if not authorized_by or not authorized_by.strip():
        raise InvalidDeletionRequestError("authorized_by is required for a deletion request")
    if deletion_basis == DeletionBasis.OTHER_AUTHORIZED_BASIS and not (
        basis_reference and basis_reference.strip()
    ):
        raise InvalidDeletionRequestError(
            "basis_reference is required when deletion_basis is OTHER_AUTHORIZED_BASIS"
        )
    if basis_reference is not None and len(basis_reference) > MAX_BASIS_REFERENCE_LENGTH:
        raise InvalidDeletionRequestError(
            f"basis_reference must not exceed {MAX_BASIS_REFERENCE_LENGTH} characters"
        )
