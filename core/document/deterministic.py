"""DP-002 Phase 1: deterministic capability implementations.

These prove the DocumentProcessor orchestration/lineage/persistence
path -- they are NOT a stand-in for real quality/classification models
and must not be mistaken for one. Both have an easily-triggered path to
their *unsatisfying* outcome as well as their happy path, deliberately:
Phase 1's job is to prove DOCUMENT_QUALITY=FAIL and
DOCUMENT_CLASSIFICATION=FAIL/DOCUMENT_UNSUPPORTED flow correctly
through to policy evaluation, not just the PASS case.
"""

from core.document.capabilities import DocumentClassifier, QualityAssessor
from core.document.types import DocumentClassification, QualityAssessment
from core.evidence_result.enums import DocumentType

# A pure, content-independent stand-in signal -- never a real blur/glare/
# crop model. Content below this size cannot plausibly be a real document
# photo; this exists to exercise DocumentProcessor's PASS/FAIL mapping,
# not to assess real image quality.
_MINIMUM_PLAUSIBLE_SIZE_BYTES = 1024

# Fixed, inspectable byte markers -- not ML, not a real classifier. A
# real DocumentClassifier (Phase 3+) replaces this entirely; this one
# exists to prove the pipeline, including its DOCUMENT_UNSUPPORTED path.
_CLASSIFICATION_MARKERS: dict[bytes, DocumentType] = {
    b"PAXLI_TEST_STANDARD_NIN_SLIP": DocumentType.STANDARD_NIN_SLIP,
    b"PAXLI_TEST_IMPROVED_NIN_SLIP": DocumentType.IMPROVED_NIN_SLIP,
    b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE": DocumentType.ICAO_PASSPORT_DATA_PAGE,
}


class DeterministicQualityAssessor(QualityAssessor):
    async def assess(self, image: bytes) -> QualityAssessment:
        score = 1.0 if len(image) >= _MINIMUM_PLAUSIBLE_SIZE_BYTES else 0.0
        return QualityAssessment(quality_score=score)


class DeterministicDocumentClassifier(DocumentClassifier):
    async def classify(self, image: bytes) -> DocumentClassification:
        for marker, document_type in _CLASSIFICATION_MARKERS.items():
            if marker in image:
                return DocumentClassification(document_type=document_type, confidence=1.0)
        return DocumentClassification(document_type=None, confidence=None)
