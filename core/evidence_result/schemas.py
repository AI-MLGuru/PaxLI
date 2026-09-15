"""Per-type `result` payload shapes (EVD-3.24 validation boundary).

These encode data SHAPES only -- never algorithm logic. Nothing here knows
how to compute a face match; it only knows what a valid FaceMatch result
looks like once something (not yet built) produces one.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator

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
    """BP-001.5 Decision 20. `reference_evidence_result_id`/
    `probe_evidence_result_id` are read by FACE_MATCH-specific
    consumers that need the role, not just the parent set --
    `parent_evidence_result_ids` (on the wrapping EvidenceResult)
    stays generic, evidence-type-agnostic lineage, read by machinery
    that must remain ignorant of what "reference"/"probe" even mean.
    Duplication between the two is intentional, not an oversight.

    This model enforces only the payload-local invariant it can see
    (distinctness) -- it never contains parent_evidence_result_ids, so
    the two membership invariants (reference/probe each present in the
    envelope's own parent set) are enforced at the envelope boundary
    instead, by validate_result_payload() below."""

    similarity: float
    reference_evidence_result_id: UUID
    probe_evidence_result_id: UUID

    @model_validator(mode="after")
    def _reference_and_probe_are_distinct(self) -> "FaceMatchResult":
        if self.reference_evidence_result_id == self.probe_evidence_result_id:
            raise ValueError(
                "reference_evidence_result_id and probe_evidence_result_id must differ"
            )
        return self


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
    raw: str
    fields: dict[str, str]


class DocumentFieldExtractionResult(BaseModel):
    """DP-001 Decision 7, as amended by Addendum A (via DP-008/DP-009).
    Canonical fields are null when not applicable to the document type or
    when no source could reliably establish them -- undifferentiated,
    per Decision 7's own original text. `extensions` carries no
    Phase 4 content (DP-009 §7.3): the deterministic reconciler always
    produces `extensions = {}`, since only the eight canonical fields
    are reconciled. `conflicted_fields` names exactly which canonical
    fields are null specifically because of unresolved cross-source
    disagreement -- a field listed here MUST be null; null alone never
    implies a field is listed (DP-008 §3.5)."""

    full_name: str | None
    surname: str | None
    given_names: str | None
    date_of_birth: str | None
    sex: str | None
    document_number: str | None
    nationality: str | None
    expiry_date: str | None
    extensions: dict[str, str]
    conflicted_fields: tuple[str, ...] = ()


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
    EvidenceResultType.FACE_DETECTION_REFERENCE: FaceDetectionResult,
    EvidenceResultType.FACE_DETECTION_PROBE: FaceDetectionResult,
    EvidenceResultType.FACE_QUALITY_REFERENCE: FaceQualityResult,
    EvidenceResultType.FACE_QUALITY_PROBE: FaceQualityResult,
    EvidenceResultType.FACE_EMBEDDING_REFERENCE: FaceEmbeddingResult,
    EvidenceResultType.FACE_EMBEDDING_PROBE: FaceEmbeddingResult,
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
    evidence_type: EvidenceResultType,
    result: dict[str, Any] | None,
    parent_evidence_result_ids: tuple[UUID, ...] = (),
) -> None:
    """Raises InvalidEvidenceResultError if `result` doesn't match the
    registered schema for `evidence_type`.

    A None result is always allowed (e.g. for NOT_REQUIRED/NOT_SUBMITTED/
    UNAVAILABLE statuses, where there is nothing to report).

    `parent_evidence_result_ids` is used only for FACE_MATCH (BP-001.5
    Decision 20's two membership invariants) -- every other evidence
    type's validation is completely unaffected by this parameter;
    passing it for a non-FACE_MATCH type is harmless (it is simply
    never read). This is the one point EvidenceResultService.create()/
    supersede() already hold both the payload and the envelope's
    parent set together, so it is where the envelope/payload
    relationship gets validated, distinct from FaceMatchResult's own
    payload-local distinctness invariant.
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

    if evidence_type is EvidenceResultType.FACE_MATCH:
        _validate_face_match_provenance(result, parent_evidence_result_ids)


def _validate_face_match_provenance(
    result: dict[str, Any], parent_evidence_result_ids: tuple[UUID, ...]
) -> None:
    """BP-001.5 Decision 20's two cross-object invariants --
    FaceMatchResult itself cannot enforce these (it never sees
    parent_evidence_result_ids), so they live here, at the one point
    both the validated payload and the envelope's parent set are
    already in scope together."""
    reference_id = UUID(str(result["reference_evidence_result_id"]))
    probe_id = UUID(str(result["probe_evidence_result_id"]))
    if reference_id not in parent_evidence_result_ids:
        raise InvalidEvidenceResultError(
            f"reference_evidence_result_id={reference_id!s} is not in "
            "parent_evidence_result_ids"
        )
    if probe_id not in parent_evidence_result_ids:
        raise InvalidEvidenceResultError(
            f"probe_evidence_result_id={probe_id!s} is not in parent_evidence_result_ids"
        )
