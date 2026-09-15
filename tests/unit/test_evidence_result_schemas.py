from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.evidence_result.enums import EvidenceResultType
from core.evidence_result.exceptions import InvalidEvidenceResultError
from core.evidence_result.schemas import SCHEMA_REGISTRY, FaceMatchResult, validate_result_payload


def test_none_result_is_always_valid_regardless_of_type() -> None:
    for evidence_type in EvidenceResultType:
        validate_result_payload(evidence_type, None)  # must not raise


def test_valid_face_match_payload_passes() -> None:
    reference_id = uuid4()
    probe_id = uuid4()
    validate_result_payload(
        EvidenceResultType.FACE_MATCH,
        {
            "similarity": 0.83,
            "reference_evidence_result_id": str(reference_id),
            "probe_evidence_result_id": str(probe_id),
        },
        (reference_id, probe_id),
    )


def test_face_match_payload_missing_required_field_is_rejected() -> None:
    """`similarity` specifically omitted -- the other two required
    fields are present, isolating this as a test of the missing-field
    case alone, not a coincidental multi-field failure."""
    reference_id = uuid4()
    probe_id = uuid4()
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(
            EvidenceResultType.FACE_MATCH,
            {
                "reference_evidence_result_id": str(reference_id),
                "probe_evidence_result_id": str(probe_id),
            },
            (reference_id, probe_id),
        )


def test_face_match_payload_with_wrong_type_is_rejected() -> None:
    """`similarity` specifically wrong-typed -- both role fields are
    otherwise valid, isolating this as a test of the wrong-type case
    alone."""
    reference_id = uuid4()
    probe_id = uuid4()
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(
            EvidenceResultType.FACE_MATCH,
            {
                "similarity": "not-a-number",
                "reference_evidence_result_id": str(reference_id),
                "probe_evidence_result_id": str(probe_id),
            },
            (reference_id, probe_id),
        )


def test_face_match_reference_id_not_in_parents_is_rejected() -> None:
    """BP-001.5 Decision 20's first membership invariant, exercised at
    the envelope boundary validate_result_payload() owns -- the
    reference id is absent from parent_evidence_result_ids even though
    the probe id is present."""
    reference_id = uuid4()
    probe_id = uuid4()
    other_id = uuid4()
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(
            EvidenceResultType.FACE_MATCH,
            {
                "similarity": 0.83,
                "reference_evidence_result_id": str(reference_id),
                "probe_evidence_result_id": str(probe_id),
            },
            (other_id, probe_id),
        )


def test_face_match_probe_id_not_in_parents_is_rejected() -> None:
    """The second membership invariant -- the probe id is absent from
    parent_evidence_result_ids even though the reference id is
    present."""
    reference_id = uuid4()
    probe_id = uuid4()
    other_id = uuid4()
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(
            EvidenceResultType.FACE_MATCH,
            {
                "similarity": 0.83,
                "reference_evidence_result_id": str(reference_id),
                "probe_evidence_result_id": str(probe_id),
            },
            (reference_id, other_id),
        )


def test_face_match_result_rejects_identical_reference_and_probe_ids() -> None:
    """The payload-local invariant FaceMatchResult itself enforces --
    distinctness, the one thing it can check without ever seeing
    parent_evidence_result_ids."""
    same_id = uuid4()
    with pytest.raises(ValidationError):
        FaceMatchResult(
            similarity=0.83, reference_evidence_result_id=same_id, probe_evidence_result_id=same_id
        )


def test_face_match_result_accepts_distinct_reference_and_probe_ids() -> None:
    result = FaceMatchResult(
        similarity=0.83, reference_evidence_result_id=uuid4(), probe_evidence_result_id=uuid4()
    )
    assert result.similarity == 0.83


def test_every_evidence_type_has_a_registered_schema() -> None:
    """Every type in the taxonomy must have a validation contract -- an
    unregistered type would silently accept any payload shape."""
    for evidence_type in EvidenceResultType:
        assert evidence_type in SCHEMA_REGISTRY


@pytest.mark.parametrize(
    "evidence_type",
    [EvidenceResultType.FACE_EMBEDDING_REFERENCE, EvidenceResultType.FACE_EMBEDDING_PROBE],
)
def test_valid_face_embedding_payload_passes(evidence_type: EvidenceResultType) -> None:
    """FaceEmbeddingResult's payload shape is shared by both role-
    qualified types (BD-001.4 H.1) -- proven here for both, not just
    one arbitrary variant."""
    validate_result_payload(
        evidence_type,
        {"embedding": [0.1, 0.2, 0.3], "embedding_dimensions": 3},
    )


def test_valid_ocr_extraction_payload_passes() -> None:
    validate_result_payload(
        EvidenceResultType.OCR_EXTRACTION,
        {"raw": "CANARY RAW TEXT", "fields": {"name": "CANARY_NAME"}},
    )


def test_valid_document_field_extraction_payload_passes() -> None:
    """DP-001 Decision 7, as amended by Addendum A (via DP-008/DP-009):
    all eight canonical fields are required (though individually
    nullable), plus extensions and conflicted_fields."""
    validate_result_payload(
        EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
        {
            "full_name": "CANARY NAME",
            "surname": None,
            "given_names": None,
            "date_of_birth": None,
            "sex": None,
            "document_number": None,
            "nationality": None,
            "expiry_date": None,
            "extensions": {},
            "conflicted_fields": [],
        },
    )


def test_document_field_extraction_payload_missing_canonical_field_is_rejected() -> None:
    """Canonical fields are required-but-nullable, never omittable --
    DP-001 Decision 7's own explicit "null rather than omitted" rule."""
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(
            EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
            {
                "full_name": None,
                "surname": None,
                "given_names": None,
                "date_of_birth": None,
                "sex": None,
                "document_number": None,
                "nationality": None,
                # expiry_date omitted
                "extensions": {},
            },
        )
