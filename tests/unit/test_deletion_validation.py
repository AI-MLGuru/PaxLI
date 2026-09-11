import pytest

from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import InvalidDeletionRequestError
from core.deletion.validation import MAX_BASIS_REFERENCE_LENGTH, validate_deletion_request


def test_valid_request_with_tenant_request_basis_passes() -> None:
    validate_deletion_request(
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        basis_reference=None,
        authorized_by="admin-1",
    )


def test_valid_request_with_data_subject_request_basis_passes() -> None:
    validate_deletion_request(
        deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,
        basis_reference="ticket-123",
        authorized_by="admin-1",
    )


@pytest.mark.parametrize("authorized_by", ["", "   ", None])
def test_missing_authorized_by_is_rejected(authorized_by: str | None) -> None:
    with pytest.raises(InvalidDeletionRequestError, match="authorized_by"):
        validate_deletion_request(
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by=authorized_by,  # type: ignore[arg-type]
        )


def test_other_authorized_basis_without_reference_is_rejected() -> None:
    """OTHER_AUTHORIZED_BASIS is deliberately the least self-explanatory
    value in the vocabulary -- using it without a reference would make the
    audit trail meaningless."""
    with pytest.raises(InvalidDeletionRequestError, match="basis_reference"):
        validate_deletion_request(
            deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
            basis_reference=None,
            authorized_by="admin-1",
        )


def test_other_authorized_basis_with_blank_reference_is_rejected() -> None:
    with pytest.raises(InvalidDeletionRequestError, match="basis_reference"):
        validate_deletion_request(
            deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
            basis_reference="   ",
            authorized_by="admin-1",
        )


def test_other_authorized_basis_with_reference_passes() -> None:
    validate_deletion_request(
        deletion_basis=DeletionBasis.OTHER_AUTHORIZED_BASIS,
        basis_reference="board-approved-erasure-2026-04",
        authorized_by="admin-1",
    )


def test_overlong_basis_reference_is_rejected() -> None:
    with pytest.raises(InvalidDeletionRequestError, match="must not exceed"):
        validate_deletion_request(
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference="x" * (MAX_BASIS_REFERENCE_LENGTH + 1),
            authorized_by="admin-1",
        )


def test_basis_reference_at_the_length_limit_passes() -> None:
    validate_deletion_request(
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        basis_reference="x" * MAX_BASIS_REFERENCE_LENGTH,
        authorized_by="admin-1",
    )
