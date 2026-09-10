from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult


def test_evidence_result_constructs_with_minimal_required_fields() -> None:
    result = EvidenceResult(
        tenant_id="tenant-a",
        session_id=uuid4(),
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="face-provider",
        producer_version="1.0.0",
        integrity_reference="deadbeef",
    )
    assert result.id is not None
    assert result.result is None
    assert result.reason_codes == ()
    assert result.parent_evidence_result_ids == ()
    assert result.supersedes_id is None


def test_evidence_result_status_is_a_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        EvidenceResult(
            tenant_id="tenant-a",
            session_id=uuid4(),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status="MAYBE",  # type: ignore[arg-type]
            producer="face-provider",
            producer_version="1.0.0",
            integrity_reference="deadbeef",
        )


def test_evidence_result_status_enum_has_exactly_the_part_iii_vocabulary() -> None:
    assert {member.value for member in EvidenceResultStatus} == {
        "NOT_REQUIRED",
        "NOT_SUBMITTED",
        "UNAVAILABLE",
        "INCONCLUSIVE",
        "PASS",
        "FAIL",
    }


def test_evidence_result_status_does_not_share_values_with_verification_status() -> None:
    """Constitutional check: an evidence result must never be representable
    as a verification decision. VERIFIED/REJECTED/REVIEW_REQUIRED are
    decision-only outcomes and must not appear in the evidence vocabulary."""
    from core.verification.enums import VerificationStatus

    evidence_values = {member.value for member in EvidenceResultStatus}
    decision_only_values = {
        VerificationStatus.VERIFIED.value,
        VerificationStatus.REJECTED.value,
        VerificationStatus.REVIEW_REQUIRED.value,
    }
    assert evidence_values.isdisjoint(decision_only_values)
