"""DP-002 Phase 1: DeterministicQualityAssessor/DeterministicDocumentClassifier
are pure, content-independent stand-ins that prove DocumentProcessor's
orchestration/lineage/persistence path -- never real quality/classification
models. Both the PASS/happy path and the FAIL/unsupported path are
exercised deliberately, not just the happy one (DP-002 §2)."""

import pytest

from core.document.deterministic import (
    DeterministicDocumentClassifier,
    DeterministicQualityAssessor,
)
from core.evidence_result.enums import DocumentType

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


@pytest.mark.asyncio
async def test_quality_assessor_passes_plausibly_sized_content() -> None:
    assessor = DeterministicQualityAssessor()
    assessment = await assessor.assess(MINIMAL_JPEG_BYTES + b"0" * 2000)
    assert assessment.quality_score == 1.0


@pytest.mark.asyncio
async def test_quality_assessor_fails_implausibly_small_content() -> None:
    assessor = DeterministicQualityAssessor()
    assessment = await assessor.assess(MINIMAL_JPEG_BYTES)
    assert assessment.quality_score == 0.0


@pytest.mark.asyncio
async def test_classifier_recognizes_each_catalog_member() -> None:
    classifier = DeterministicDocumentClassifier()
    for marker, expected in (
        (b"PAXLI_TEST_STANDARD_NIN_SLIP", DocumentType.STANDARD_NIN_SLIP),
        (b"PAXLI_TEST_IMPROVED_NIN_SLIP", DocumentType.IMPROVED_NIN_SLIP),
        (b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE", DocumentType.ICAO_PASSPORT_DATA_PAGE),
    ):
        classification = await classifier.classify(MINIMAL_JPEG_BYTES + marker)
        assert classification.document_type is expected
        assert classification.confidence == 1.0


@pytest.mark.asyncio
async def test_classifier_reports_unrecognized_document_as_none() -> None:
    """The DOCUMENT_UNSUPPORTED path (DP-001 Decision 5) must be
    deliberately reachable, not just the happy path."""
    classifier = DeterministicDocumentClassifier()
    classification = await classifier.classify(MINIMAL_JPEG_BYTES + b"not a known document")
    assert classification.document_type is None
    assert classification.confidence is None
