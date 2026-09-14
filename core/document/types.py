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
    "CANONICAL_FIELD_NAMES",
    "DocumentClassification",
    "DocumentType",
    "FieldReconciliationResult",
    "MRZExtraction",
    "MRZReadOutcome",
    "MRZReadResult",
    "OCRExtraction",
    "OCRReadOutcome",
    "OCRReadResult",
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
    """Pure extracted data -- DP-005 Decision 7. Carries no outcome/status
    information of its own; see OCRReadOutcome/OCRReadResult below for how
    an extraction attempt's outcome is expressed. `fields` is source-
    specific, non-canonical -- only DOCUMENT_FIELD_EXTRACTION (Phase 4)
    gets the hybrid canonical schema."""

    raw: str
    fields: dict[str, str]


class OCRReadOutcome(StrEnum):
    """Explicit domain-level pipeline outcome for one OCR attempt (DP-005
    Decisions 1/2). Deliberately NOT EvidenceResultStatus -- core/document/
    MUST NOT import or produce EvidenceResultStatus directly (DP-001
    Decision 3's domain/persistence boundary); DocumentProcessor alone
    translates this into an EvidenceResultStatus + reason code, via the
    explicit table in infrastructure/document/processor.py, never by
    inference. No FAIL/MALFORMED members exist -- OCR has no standards-
    defined negative condition and no structural grammar to violate
    (DP-005 Decision 2)."""

    UNREADABLE = "UNREADABLE"
    VALID = "VALID"


@dataclass(frozen=True)
class OCRReadResult:
    """Returned by OCREngine.extract() -- always, never None (DP-005
    Decision 3: OCR has no capability-level absence/not-applicable state;
    a document image is inherently an OCR input, unlike an MRZ zone or a
    barcode symbol that may genuinely be physically absent). `extraction`
    is None exactly when outcome=UNREADABLE."""

    outcome: OCRReadOutcome
    extraction: OCRExtraction | None


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


CANONICAL_FIELD_NAMES = (
    "full_name",
    "surname",
    "given_names",
    "date_of_birth",
    "sex",
    "document_number",
    "nationality",
    "expiry_date",
)


@dataclass(frozen=True)
class FieldReconciliationResult:
    """Returned by DocumentFieldReconciler.reconcile() -- DP-008/DP-009
    Phase 4. Always populated, never None: DOCUMENT_FIELD_EXTRACTION has
    no capability-level absence state of its own (mirrors OCRReadResult's
    non-optional contract) -- whether this stage runs at all is decided
    entirely by DocumentProcessor's existing ambiguous-capture
    precondition, not by anything this type represents.

    `extensions` carries no Phase 4 content -- the reconciler reconciles
    only the eight canonical fields (DP-009 §7.3); it is never populated
    from source-specific fields outside that vocabulary.

    `conflicted_fields` names exactly which canonical fields are null
    specifically because two or more usable sources disagreed on their
    normalized value (DP-008 §3.5/§3.7) -- never because a field was
    merely not applicable or not established by any source. The
    invariant is one-directional and enforced below, not left as a
    documentation-only promise: a listed field MUST be null; null alone
    never implies a field is listed."""

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

    def __post_init__(self) -> None:
        unknown = set(self.conflicted_fields) - set(CANONICAL_FIELD_NAMES)
        if unknown:
            raise ValueError(
                f"conflicted_fields contains non-canonical names: {sorted(unknown)}"
            )
        for name in self.conflicted_fields:
            if getattr(self, name) is not None:
                raise ValueError(
                    f"conflicted_fields lists {name!r} but its value is not null "
                    "(DP-008 §3.5: a listed field MUST be null)"
                )
