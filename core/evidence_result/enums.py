from enum import StrEnum


class EvidenceResultStatus(StrEnum):
    """Part III §3.6 closed vocabulary.

    Deliberately independent of core.verification.enums.VerificationStatus:
    an evidence result must never be representable as, or coupled to, a
    verification decision (constitutional separation between evidence and
    decision -- see core/evidence_result/models.py).
    """

    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_SUBMITTED = "NOT_SUBMITTED"
    UNAVAILABLE = "UNAVAILABLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    PASS = "PASS"
    FAIL = "FAIL"


class EvidenceResultType(StrEnum):
    """Part III §3.5 taxonomy.

    v1.0-active subset, plus LIVENESS_ASSESSMENT defined per the spec's own
    `TARGET: v1.1` status for liveness (Part III §3.33) -- declared here so
    the taxonomy is complete, but nothing is required or expected to
    produce it yet.

    BD-001.4/BD-001.5 (Slice H): FACE_DETECTION/FACE_QUALITY/FACE_EMBEDDING
    are role-qualified into REFERENCE/PROBE pairs, not left as three bare
    members -- BiometricProcessor (Slice G.2) needs two simultaneously
    effective embeddings per session (one reference, one probe), which
    the database's own partial unique index
    (ix_evidence_results_one_effective_per_type, scoped to
    (tenant_id, session_id, evidence_type)) cannot represent under a
    single undifferentiated FACE_EMBEDDING member. Each pair shares one
    payload schema (FaceDetectionResult/FaceQualityResult/
    FaceEmbeddingResult, core.evidence_result.schemas) -- only the type
    key is role-qualified, never the payload shape. No production code
    has ever persisted a row of any of the three original bare members
    (confirmed before this change), so this is a pure taxonomy
    completion, not a live data migration.
    """

    FACE_DETECTION_REFERENCE = "FACE_DETECTION_REFERENCE"
    FACE_DETECTION_PROBE = "FACE_DETECTION_PROBE"
    FACE_QUALITY_REFERENCE = "FACE_QUALITY_REFERENCE"
    FACE_QUALITY_PROBE = "FACE_QUALITY_PROBE"
    FACE_EMBEDDING_REFERENCE = "FACE_EMBEDDING_REFERENCE"
    FACE_EMBEDDING_PROBE = "FACE_EMBEDDING_PROBE"
    FACE_MATCH = "FACE_MATCH"
    DOCUMENT_QUALITY = "DOCUMENT_QUALITY"
    DOCUMENT_CLASSIFICATION = "DOCUMENT_CLASSIFICATION"
    OCR_EXTRACTION = "OCR_EXTRACTION"
    DOCUMENT_FIELD_EXTRACTION = "DOCUMENT_FIELD_EXTRACTION"
    MRZ = "MRZ"
    BARCODE_QR = "BARCODE_QR"
    DOCUMENT_AUTHENTICITY = "DOCUMENT_AUTHENTICITY"
    IDENTITY_CONSISTENCY = "IDENTITY_CONSISTENCY"
    EXTERNAL_IDENTITY_PROVIDER = "EXTERNAL_IDENTITY_PROVIDER"
    LIVENESS_ASSESSMENT = "LIVENESS_ASSESSMENT"


class DocumentType(StrEnum):
    """DP-001 Decision 5: PaxLI V1's closed document-type catalog -- the
    leaf/variant value DocumentClassificationResult.document_type
    carries. "Family" (NIN_SLIP, ICAO_PASSPORT) is a derived grouping
    concept for documentation/conformance purposes only, never persisted
    as a second field -- downstream extraction rules key off the specific
    leaf variant regardless.

    Absence of a match (an unrecognized/unsupported document) is
    represented at the EvidenceResultStatus level -- DOCUMENT_CLASSIFICATION
    status=FAIL, reason_codes=("DOCUMENT_UNSUPPORTED",), result=None --
    never as a member of this enum. `UNSUPPORTED` is an outcome, not a
    document type.
    """

    STANDARD_NIN_SLIP = "STANDARD_NIN_SLIP"
    IMPROVED_NIN_SLIP = "IMPROVED_NIN_SLIP"
    ICAO_PASSPORT_DATA_PAGE = "ICAO_PASSPORT_DATA_PAGE"
