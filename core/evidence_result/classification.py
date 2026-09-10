"""Server-side evidence_type -> DataClassification mapping.

This is the mechanism that satisfies "classification must be determined by
Averiq's server-side policy, never by a caller-provided value": the public
EvidenceResultService.create() signature has no classification parameter
at all -- classify() is the only source of truth, keyed by evidence_type.

Mapping is aligned with the field-level precedent already established in
core/security/classification.py: extracted identity field VALUES (OCR,
MRZ, document fields -- comparable to existing "name"/"document_number"
SENSITIVE fields) are SENSITIVE; a persistent biometric embedding
(comparable to the existing "embedding"/"face_embedding" HIGHLY_SENSITIVE
fields) is HIGHLY_SENSITIVE. This is an initial, defensible mapping, not a
final security-reviewed one -- flagged in the Foundation-008 closure record.
"""

from core.evidence_result.enums import EvidenceResultType
from core.security.classification import DataClassification

EVIDENCE_RESULT_CLASSIFICATION: dict[EvidenceResultType, DataClassification] = {
    EvidenceResultType.FACE_DETECTION: DataClassification.SENSITIVE,
    EvidenceResultType.FACE_QUALITY: DataClassification.SENSITIVE,
    EvidenceResultType.FACE_EMBEDDING: DataClassification.HIGHLY_SENSITIVE,
    EvidenceResultType.FACE_MATCH: DataClassification.SENSITIVE,
    EvidenceResultType.DOCUMENT_QUALITY: DataClassification.SENSITIVE,
    EvidenceResultType.DOCUMENT_CLASSIFICATION: DataClassification.SENSITIVE,
    EvidenceResultType.OCR_EXTRACTION: DataClassification.SENSITIVE,
    EvidenceResultType.DOCUMENT_FIELD_EXTRACTION: DataClassification.SENSITIVE,
    EvidenceResultType.MRZ: DataClassification.SENSITIVE,
    EvidenceResultType.BARCODE_QR: DataClassification.SENSITIVE,
    EvidenceResultType.DOCUMENT_AUTHENTICITY: DataClassification.SENSITIVE,
    EvidenceResultType.IDENTITY_CONSISTENCY: DataClassification.SENSITIVE,
    EvidenceResultType.EXTERNAL_IDENTITY_PROVIDER: DataClassification.SENSITIVE,
    EvidenceResultType.LIVENESS_ASSESSMENT: DataClassification.SENSITIVE,
}


def classify(evidence_type: EvidenceResultType) -> DataClassification:
    return EVIDENCE_RESULT_CLASSIFICATION.get(evidence_type, DataClassification.SENSITIVE)
