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
