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
    """

    FACE_DETECTION = "FACE_DETECTION"
    FACE_QUALITY = "FACE_QUALITY"
    FACE_EMBEDDING = "FACE_EMBEDDING"
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
