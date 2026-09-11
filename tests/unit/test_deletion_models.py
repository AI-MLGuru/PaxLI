from uuid import uuid4

from core.deletion.enums import DeletionBasis
from core.evidence.models import EvidenceTombstone
from core.evidence_result.models import EvidenceResultTombstone


def test_evidence_tombstone_constructs_with_requested_at_and_no_executed_at() -> None:
    """A freshly requested tombstone is a truthful, incomplete state --
    executed_at must not default to "now" or anything else that could be
    mistaken for completion (Invariant-06 remediation review)."""
    tombstone = EvidenceTombstone(
        evidence_id=uuid4(),
        session_id=uuid4(),
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.TENANT_REQUEST,
        authorized_by="admin-1",
        evidence_integrity_reference="deadbeef",
    )
    assert tombstone.requested_at is not None
    assert tombstone.executed_at is None


def test_evidence_tombstone_has_no_field_capable_of_holding_raw_content() -> None:
    """PRV-11.30.1: tombstones MUST NOT contain deleted biometric or
    document content. Structural proof, not just a documented intention --
    the model has no field shaped to hold it in the first place."""
    field_names = set(EvidenceTombstone.model_fields.keys())
    forbidden = {"content", "image", "bytes", "object_key", "mime_type", "size_bytes"}
    assert field_names.isdisjoint(forbidden)


def test_evidence_result_tombstone_constructs_with_requested_at_and_no_executed_at() -> None:
    tombstone = EvidenceResultTombstone(
        evidence_result_id=uuid4(),
        session_id=uuid4(),
        tenant_id="tenant-a",
        deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,
        authorized_by="admin-1",
        evidence_integrity_reference="deadbeef",
    )
    assert tombstone.requested_at is not None
    assert tombstone.executed_at is None


def test_evidence_result_tombstone_has_no_result_field() -> None:
    """PRV-11.30.1 / explicit Foundation review instruction: the tombstone
    must remain metadata-only, never duplicating the sensitive result
    payload it commemorates the deletion of."""
    field_names = set(EvidenceResultTombstone.model_fields.keys())
    assert "result" not in field_names


def test_deletion_basis_is_exactly_the_approved_closed_vocabulary() -> None:
    assert {member.value for member in DeletionBasis} == {
        "TENANT_REQUEST",
        "DATA_SUBJECT_REQUEST",
        "RETENTION_EXPIRY",
        "LEGAL_REQUIREMENT",
        "OTHER_AUTHORIZED_BASIS",
    }
