"""DP-001 Decisions 3/5/7: the domain-level shapes a document-processing
capability returns -- never an EvidenceResult, never a Pydantic
persistence schema. core.document.processor's DocumentProcessor is the
only thing that translates these into typed, lineage-bearing
EvidenceResult rows; a capability implementation never touches
persistence itself.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from core.evidence_result.enums import DocumentType

__all__ = [
    "BarcodeExtraction",
    "BarcodeReadOutcome",
    "BarcodeReadResult",
    "DocumentClassification",
    "DocumentType",
    "MRZExtraction",
    "MRZReadOutcome",
    "MRZReadResult",
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
    """Pure extracted data -- DP-003 Decision 5. Carries no outcome/status
    information of its own; see MRZReadOutcome/MRZReadResult below for how
    a parse attempt's outcome is expressed."""

    raw: str
    fields: dict[str, str]


class MRZReadOutcome(StrEnum):
    """Explicit domain-level pipeline outcome for one MRZ zone-detection
    attempt (DP-004 §3, reconciled). Deliberately NOT EvidenceResultStatus
    -- core/document/ MUST NOT import or produce EvidenceResultStatus
    directly (DP-001 Decision 3's domain/persistence boundary);
    DocumentProcessor alone translates this into an EvidenceResultStatus +
    reason code, via the explicit table in infrastructure/document/
    processor.py, never by inference from MRZExtraction's shape."""

    UNREADABLE = "UNREADABLE"
    MALFORMED = "MALFORMED"
    CHECK_DIGIT_MISMATCH = "CHECK_DIGIT_MISMATCH"
    VALID = "VALID"


@dataclass(frozen=True)
class MRZReadResult:
    """Returned by MRZParser.parse() whenever a zone was found at all
    (parse() still returns bare None for "no zone present whatsoever" ->
    MRZ=NOT_SUBMITTED, unchanged from Phase 1's interface). `extraction`
    is None exactly when outcome=UNREADABLE (nothing meaningful was
    extracted to wrap); populated for MALFORMED (raw text, no parsed
    fields), CHECK_DIGIT_MISMATCH and VALID (raw text plus parsed fields
    in both cases -- MALFORMED vs CHECK_DIGIT_MISMATCH is never
    distinguished by whether fields is populated, only by outcome)."""

    outcome: MRZReadOutcome
    extraction: MRZExtraction | None


@dataclass(frozen=True)
class BarcodeExtraction:
    """Pure extracted data -- DP-003 Decision 6. symbology uses the
    normalized producer vocabulary (e.g. QR_CODE, PDF417, CODE128) and is
    NOT policy-addressable in Phase 2."""

    raw: str
    fields: dict[str, str] = field(default_factory=dict)
    symbology: str | None = None


class BarcodeReadOutcome(StrEnum):
    """No FAIL-equivalent member exists -- DP-003 Decision 2 forbids
    BARCODE_QR from ever reaching FAIL; there is no outcome for
    DocumentProcessor to map to it even if it tried."""

    UNREADABLE = "UNREADABLE"
    PAYLOAD_UNRECOGNIZED = "PAYLOAD_UNRECOGNIZED"
    PAYLOAD_MALFORMED = "PAYLOAD_MALFORMED"
    VALID = "VALID"


@dataclass(frozen=True)
class BarcodeReadResult:
    outcome: BarcodeReadOutcome
    extraction: BarcodeExtraction | None  # None exactly when outcome=UNREADABLE
