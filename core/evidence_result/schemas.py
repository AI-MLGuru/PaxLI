"""Per-type `result` payload shapes (EVD-3.24 validation boundary).

These encode data SHAPES only -- never algorithm logic. Nothing here knows
how to compute a face match; it only knows what a valid FaceMatch result
looks like once something (not yet built) produces one.
"""

from typing import Any

from pydantic import BaseModel

from core.evidence_result.enums import DocumentType, EvidenceResultType
from core.evidence_result.exceptions import InvalidEvidenceResultError


class FaceDetectionResult(BaseModel):
    detected: bool
    face_count: int | None = None


class FaceQualityResult(BaseModel):
    quality_score: float


class FaceEmbeddingResult(BaseModel):
    embedding: tuple[float, ...]
    embedding_dimensions: int


class FaceMatchResult(BaseModel):
    similarity: float


class DocumentQualityResult(BaseModel):
    quality_score: float


class DocumentClassificationResult(BaseModel):
    """document_type is DP-001 Decision 5's controlled vocabulary, never
    a free string. An unrecognized document is represented at the
    EvidenceResultStatus level (status=FAIL, reason_codes=
    ("DOCUMENT_UNSUPPORTED",), result=None) -- never as a value of this
    field, so document_type is never optional here."""

    document_type: DocumentType


class OcrExtractionResult(BaseModel):
    fields: dict[str, str]


class DocumentFieldExtractionResult(BaseModel):
    fields: dict[str, str]


class MrzResult(BaseModel):
    raw: str
    fields: dict[str, str]


class BarcodeQrResult(BaseModel):
    raw: str
    fields: dict[str, str] = {}
    symbology: str | None = None


class DocumentAuthenticityResult(BaseModel):
    authenticity_signals: tuple[str, ...]


class IdentityConsistencyResult(BaseModel):
    consistent: bool
    mismatched_fields: tuple[str, ...] = ()


class ExternalIdentityProviderResult(BaseModel):
    provider: str
    provider_reference: str
    matched: bool | None = None


class LivenessAssessmentResult(BaseModel):
    live_score: float
    attack_score: float | None = None


SCHEMA_REGISTRY: dict[EvidenceResultType, type[BaseModel]] = {
    EvidenceResultType.FACE_DETECTION: FaceDetectionResult,
    EvidenceResultType.FACE_QUALITY: FaceQualityResult,
    EvidenceResultType.FACE_EMBEDDING: FaceEmbeddingResult,
    EvidenceResultType.FACE_MATCH: FaceMatchResult,
    EvidenceResultType.DOCUMENT_QUALITY: DocumentQualityResult,
    EvidenceResultType.DOCUMENT_CLASSIFICATION: DocumentClassificationResult,
    EvidenceResultType.OCR_EXTRACTION: OcrExtractionResult,
    EvidenceResultType.DOCUMENT_FIELD_EXTRACTION: DocumentFieldExtractionResult,
    EvidenceResultType.MRZ: MrzResult,
    EvidenceResultType.BARCODE_QR: BarcodeQrResult,
    EvidenceResultType.DOCUMENT_AUTHENTICITY: DocumentAuthenticityResult,
    EvidenceResultType.IDENTITY_CONSISTENCY: IdentityConsistencyResult,
    EvidenceResultType.EXTERNAL_IDENTITY_PROVIDER: ExternalIdentityProviderResult,
    EvidenceResultType.LIVENESS_ASSESSMENT: LivenessAssessmentResult,
}


def validate_result_payload(
    evidence_type: EvidenceResultType, result: dict[str, Any] | None
) -> None:
    """Raises InvalidEvidenceResultError if `result` doesn't match the
    registered schema for `evidence_type`.

    A None result is always allowed (e.g. for NOT_REQUIRED/NOT_SUBMITTED/
    UNAVAILABLE statuses, where there is nothing to report).
    """
    if result is None:
        return
    schema = SCHEMA_REGISTRY.get(evidence_type)
    if schema is None:
        raise InvalidEvidenceResultError(f"No registered result schema for {evidence_type.value}")
    try:
        schema.model_validate(result)
    except Exception as exception:
        raise InvalidEvidenceResultError(
            f"result payload does not match schema for {evidence_type.value}: {exception}"
        ) from exception
