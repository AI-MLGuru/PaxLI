"""BD-001 Slice G (BD-001.2): InsightFaceDocumentFaceExtractor's own
decode/cardinality/crop logic, exercised via the `app=` injection seam
so this stays a fast, hermetic unit test -- it never constructs a real
FaceAnalysis pipeline. Real, end-to-end InsightFace bbox behavior was
already confirmed live for Slice B/C; this file tests the extraction-
specific crop/re-encode logic built on top of that same, already-
validated vendor shape.
"""

from typing import Any

import cv2
import numpy as np
import pytest

from core.face.capabilities import CapabilityUnavailableError
from core.face.reason_codes import FaceReasonCode
from core.face.types import DocumentFaceExtractionOutcome
from infrastructure.face.document_face_extractor import InsightFaceDocumentFaceExtractor


def _document_image_bytes() -> bytes:
    """A genuinely valid, decodable 100x100 image with a distinct
    50x50 colored block in its lower-right quadrant (rows/cols 50-100)
    -- large enough for a meaningful bbox crop, and distinct enough to
    assert the crop's actual content against, not just its presence."""
    array = np.full((100, 100, 3), 10, dtype=np.uint8)
    array[50:100, 50:100] = (200, 150, 100)  # BGR
    ok, encoded = cv2.imencode(".jpg", array)
    assert ok
    return bytes(encoded)


class _FakeFace:
    def __init__(self, bbox: list[float]) -> None:
        self.bbox = bbox


class _FakeApp:
    """Matches only the single method extract_candidate() actually
    calls -- deliberately not a full FaceAnalysis stand-in."""

    def __init__(self, faces: list[_FakeFace]) -> None:
        self._faces = faces
        self.call_count = 0

    def get(self, image: Any) -> list[_FakeFace]:
        self.call_count += 1
        return self._faces


@pytest.mark.asyncio
async def test_extract_candidate_reports_unreadable_for_undecodable_bytes_without_calling_get() -> (
    None
):
    fake = _FakeApp([_FakeFace(bbox=[0, 0, 10, 10])])
    extractor = InsightFaceDocumentFaceExtractor(app=fake)
    result = await extractor.extract_candidate(b"not an image at all, just random bytes")
    assert result.outcome is DocumentFaceExtractionOutcome.UNREADABLE
    assert result.image is None
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_extract_candidate_reports_no_face_for_zero_faces() -> None:
    extractor = InsightFaceDocumentFaceExtractor(app=_FakeApp([]))
    result = await extractor.extract_candidate(_document_image_bytes())
    assert result.outcome is DocumentFaceExtractionOutcome.NO_FACE
    assert result.image is None


@pytest.mark.asyncio
async def test_extract_candidate_reports_ambiguous_for_multiple_faces_without_selecting_one() -> (
    None
):
    """B-2's own boundary, applied identically here: no largest-bbox
    selection, ever."""
    faces = [_FakeFace(bbox=[0, 0, 10, 10]), _FakeFace(bbox=[20, 20, 40, 40])]
    extractor = InsightFaceDocumentFaceExtractor(app=_FakeApp(faces))
    result = await extractor.extract_candidate(_document_image_bytes())
    assert result.outcome is DocumentFaceExtractionOutcome.AMBIGUOUS
    assert result.image is None


@pytest.mark.asyncio
async def test_extract_candidate_crops_exactly_the_reported_region() -> None:
    """Not just "some bytes came back" -- decodes the returned crop and
    checks both its dimensions and its actual pixel content match the
    known 50x50 colored block the bbox names, distinct from the
    image's background fill."""
    fake = _FakeApp([_FakeFace(bbox=[50, 50, 100, 100])])
    extractor = InsightFaceDocumentFaceExtractor(app=fake)
    result = await extractor.extract_candidate(_document_image_bytes())

    assert result.outcome is DocumentFaceExtractionOutcome.VALID
    assert result.image is not None
    decoded = cv2.imdecode(np.frombuffer(result.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (50, 50)
    # JPEG re-encoding introduces small lossy deviation -- assert close,
    # not exact, and clearly distinct from the background fill (10,10,10).
    mean_color = decoded.reshape(-1, 3).mean(axis=0)
    assert np.allclose(mean_color, (200, 150, 100), atol=5)


@pytest.mark.asyncio
async def test_extract_candidate_crops_to_bbox_clipped_to_image_bounds() -> None:
    """A bbox extending past the image edge must not raise -- detector
    boxes can legitimately do this in practice."""
    fake = _FakeApp([_FakeFace(bbox=[-5, -5, 200, 200])])
    extractor = InsightFaceDocumentFaceExtractor(app=fake)
    result = await extractor.extract_candidate(_document_image_bytes())
    assert result.outcome is DocumentFaceExtractionOutcome.VALID
    assert result.image is not None


@pytest.mark.asyncio
async def test_extract_candidate_raises_for_bbox_entirely_outside_image() -> None:
    """Same failure chain InsightFaceQualityAssessor's own identical
    guard documents in full: a bbox clipping to zero/negative width or
    height would otherwise slice to an EMPTY ndarray. Must raise
    explicitly instead of silently encoding a corrupted/empty crop."""
    fake = _FakeApp([_FakeFace(bbox=[150, 150, 250, 250])])
    extractor = InsightFaceDocumentFaceExtractor(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await extractor.extract_candidate(_document_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EXTRACTION_DEGENERATE_CROP.value


@pytest.mark.asyncio
async def test_extract_candidate_raises_for_degenerate_zero_width_bbox() -> None:
    """A structurally degenerate bbox (x1 == x2) inside otherwise-valid
    image bounds -- not merely an edge-clipping case."""
    fake = _FakeApp([_FakeFace(bbox=[50, 10, 50, 90])])
    extractor = InsightFaceDocumentFaceExtractor(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await extractor.extract_candidate(_document_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.EXTRACTION_DEGENERATE_CROP.value
