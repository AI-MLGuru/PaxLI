import pytest

from core.evidence_result.enums import EvidenceResultType
from core.evidence_result.exceptions import InvalidEvidenceResultError
from core.evidence_result.schemas import SCHEMA_REGISTRY, validate_result_payload


def test_none_result_is_always_valid_regardless_of_type() -> None:
    for evidence_type in EvidenceResultType:
        validate_result_payload(evidence_type, None)  # must not raise


def test_valid_face_match_payload_passes() -> None:
    validate_result_payload(EvidenceResultType.FACE_MATCH, {"similarity": 0.83})


def test_face_match_payload_missing_required_field_is_rejected() -> None:
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(EvidenceResultType.FACE_MATCH, {"wrong_field": 0.83})


def test_face_match_payload_with_wrong_type_is_rejected() -> None:
    with pytest.raises(InvalidEvidenceResultError):
        validate_result_payload(EvidenceResultType.FACE_MATCH, {"similarity": "not-a-number"})


def test_every_evidence_type_has_a_registered_schema() -> None:
    """Every type in the taxonomy must have a validation contract -- an
    unregistered type would silently accept any payload shape."""
    for evidence_type in EvidenceResultType:
        assert evidence_type in SCHEMA_REGISTRY


def test_valid_face_embedding_payload_passes() -> None:
    validate_result_payload(
        EvidenceResultType.FACE_EMBEDDING,
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
