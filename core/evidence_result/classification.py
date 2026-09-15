"""Server-side evidence_type -> DataClassification mapping.

This is the mechanism that satisfies "classification must be determined by
PaxLI's server-side policy, never by a caller-provided value": the public
EvidenceResultService.create() signature has no classification parameter
at all -- classify() is the only source of truth, keyed by evidence_type.

Classification is determined by the sensitivity of the persisted result
PAYLOAD, not merely by the evidence type's domain (docs/decisions/
DP-001-document-processing-discovery.md, Decision 1): OCR_EXTRACTION,
MRZ, BARCODE_QR, and DOCUMENT_FIELD_EXTRACTION carry raw or reconciled
identity-field VALUES and are HIGHLY_SENSITIVE; DOCUMENT_QUALITY,
DOCUMENT_CLASSIFICATION, and DOCUMENT_AUTHENTICITY carry only a
score/label/signal-name and stay SENSITIVE -- the same principle already
applied to biometrics (FACE_EMBEDDING_REFERENCE/FACE_EMBEDDING_PROBE HIGHLY_SENSITIVE vs.
FACE_QUALITY_*/FACE_MATCH/FACE_DETECTION_* SENSITIVE). EXTERNAL_IDENTITY_PROVIDER
is provisionally SENSITIVE and MUST be reassessed against this same
payload-content test once a real adapter's response shape is known. The
remaining entries are an initial, defensible mapping, not a final
security-reviewed one -- flagged in the Foundation-008 closure record.
"""

from core.evidence_result.enums import EvidenceResultType
from core.security.classification import DataClassification

EVIDENCE_RESULT_CLASSIFICATION: dict[EvidenceResultType, DataClassification] = {
    EvidenceResultType.FACE_DETECTION_REFERENCE: DataClassification.SENSITIVE,
    EvidenceResultType.FACE_DETECTION_PROBE: DataClassification.SENSITIVE,
    EvidenceResultType.FACE_QUALITY_REFERENCE: DataClassification.SENSITIVE,
    EvidenceResultType.FACE_QUALITY_PROBE: DataClassification.SENSITIVE,
    EvidenceResultType.FACE_EMBEDDING_REFERENCE: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.FACE_EMBEDDING_PROBE: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.FACE_MATCH: DataClassification.SENSITIVE,
    EvidenceResultType.DOCUMENT_QUALITY: DataClassification.SENSITIVE,
    EvidenceResultType.DOCUMENT_CLASSIFICATION: DataClassification.SENSITIVE,
    # DP-001 Decision 1: these four carry raw or reconciled identity-field
    # VALUES (OCR text, MRZ raw+parsed data, barcode payload, canonical
    # reconciled fields) -- Part XI §11.5 ("identity data... names, dates
    # of birth, identity numbers... SENSITIVE unless more restrictive
    # classification applies") plus the same payload-content principle
    # already governing biometrics (FACE_EMBEDDING HIGHLY_SENSITIVE vs.
    # FACE_QUALITY/FACE_MATCH/FACE_DETECTION SENSITIVE) puts them a tier
    # above DOCUMENT_QUALITY/DOCUMENT_CLASSIFICATION/DOCUMENT_AUTHENTICITY,
    # whose payloads carry only a score/label/signal-name, never a raw
    # identity value.
    EvidenceResultType.OCR_EXTRACTION: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.DOCUMENT_FIELD_EXTRACTION: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.MRZ: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.BARCODE_QR: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.DOCUMENT_AUTHENTICITY: DataClassification.SENSITIVE,
    EvidenceResultType.IDENTITY_CONSISTENCY: DataClassification.SENSITIVE,
    EvidenceResultType.EXTERNAL_IDENTITY_PROVIDER: DataClassification.SENSITIVE,
    EvidenceResultType.LIVENESS_ASSESSMENT: DataClassification.SENSITIVE,
}


def classify(evidence_type: EvidenceResultType) -> DataClassification:
    return EVIDENCE_RESULT_CLASSIFICATION.get(evidence_type, DataClassification.SENSITIVE)
