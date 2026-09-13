"""DP-001 Decisions 3/5/7: the domain-level shapes a document-processing
capability returns -- never an EvidenceResult, never a Pydantic
persistence schema. core.document.processor's DocumentProcessor is the
only thing that translates these into typed, lineage-bearing
EvidenceResult rows; a capability implementation never touches
persistence itself.
"""

from dataclasses import dataclass, field

from core.evidence_result.enums import DocumentType

__all__ = [
    "BarcodeExtraction",
    "DocumentClassification",
    "DocumentType",
    "MRZExtraction",
    "OCRExtraction",
    "QualityAssessment",
]


@dataclass(frozen=True)
class QualityAssessment:
    quality_score: float


@dataclass(frozen=True)
class DocumentClassification:
    """document_type=None means: no DP-001 Decision 5 catalog member
    matched. DocumentProcessor -- never this type, never the capability
    itself -- decides that this maps to DOCUMENT_CLASSIFICATION
    status=FAIL, reason_codes=("DOCUMENT_UNSUPPORTED",)."""

    document_type: DocumentType | None
    confidence: float | None = None


@dataclass(frozen=True)
class OCRExtraction:
    """Raw, per-source, non-canonical -- DP-001 Decision 7 keeps this
    shape unchanged; only DOCUMENT_FIELD_EXTRACTION (Phase 2) gets the
    hybrid canonical schema. No Phase 1 producer exists for this type."""

    fields: dict[str, str]


@dataclass(frozen=True)
class MRZExtraction:
    """No Phase 1 producer exists for this type."""

    raw: str
    fields: dict[str, str]


@dataclass(frozen=True)
class BarcodeExtraction:
    """No Phase 1 producer exists for this type."""

    raw: str
    fields: dict[str, str] = field(default_factory=dict)
