"""BD-001 Slice C: InsightFaceQualityAssessor's own decode/cardinality/
normalization logic, exercised via the `app=` injection seam so this
stays a fast, hermetic unit test -- it never constructs a real
FaceAnalysis pipeline. Real, end-to-end InsightFace behavior (bbox,
det_score) was already confirmed live for Slice B; this file tests the
quality-specific translation logic built on top of that same, already-
validated vendor shape.
"""

from typing import Any

import cv2
import numpy as np
import pytest

from core.face.capabilities import CapabilityUnavailableError
from core.face.reason_codes import FaceReasonCode
from core.face.types import FaceQualityOutcome
from infrastructure.face.insightface_adapter import InsightFaceQualityAssessor


def _real_image_bytes(fill: int = 200) -> bytes:
    """A genuinely valid, decodable image, large enough for a meaningful
    bbox crop -- assess() calls cv2.imdecode() for real."""
    array = np.full((100, 100, 3), fill, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", array)
    assert ok
    return bytes(encoded)


class _FakeFace:
    def __init__(self, bbox: list[float], det_score: float) -> None:
        self.bbox = bbox
        self.det_score = det_score


class _FakeApp:
    """Matches only the single method InsightFaceQualityAssessor.assess()
    actually calls -- deliberately not a full FaceAnalysis stand-in."""

    def __init__(self, faces: list[_FakeFace]) -> None:
        self._faces = faces
        self.call_count = 0

    def get(self, image: Any) -> list[_FakeFace]:
        self.call_count += 1
        return self._faces


@pytest.mark.asyncio
async def test_assess_reports_unreadable_for_undecodable_bytes_without_calling_get() -> None:
    fake = _FakeApp([_FakeFace(bbox=[0, 0, 10, 10], det_score=0.9)])
    assessor = InsightFaceQualityAssessor(app=fake)
    result = await assessor.assess(b"not an image at all, just random bytes")
    assert result.outcome is FaceQualityOutcome.UNREADABLE
    assert result.quality_score is None
    assert fake.call_count == 0


@pytest.mark.asyncio
async def test_assess_reports_no_face_for_zero_faces() -> None:
    assessor = InsightFaceQualityAssessor(app=_FakeApp([]))
    result = await assessor.assess(_real_image_bytes())
    assert result.outcome is FaceQualityOutcome.NO_FACE
    assert result.quality_score is None


@pytest.mark.asyncio
async def test_assess_reports_ambiguous_for_multiple_faces_without_selecting_one() -> None:
    """B-2's own boundary, applied identically to the quality capability:
    no largest-bbox/highest-det_score selection, ever."""
    faces = [
        _FakeFace(bbox=[0, 0, 10, 10], det_score=0.9),
        _FakeFace(bbox=[20, 20, 40, 40], det_score=0.5),
    ]
    assessor = InsightFaceQualityAssessor(app=_FakeApp(faces))
    result = await assessor.assess(_real_image_bytes())
    assert result.outcome is FaceQualityOutcome.AMBIGUOUS
    assert result.quality_score is None


@pytest.mark.asyncio
async def test_assess_reports_valid_with_bounded_quality_score() -> None:
    fake = _FakeApp([_FakeFace(bbox=[10, 10, 90, 90], det_score=0.8)])
    assessor = InsightFaceQualityAssessor(app=fake)
    result = await assessor.assess(_real_image_bytes())
    assert result.outcome is FaceQualityOutcome.VALID
    assert result.quality_score is not None
    assert 0.0 <= result.quality_score <= 1.0
    assert fake.call_count == 1


@pytest.mark.asyncio
async def test_assess_quality_score_reflects_det_score_component() -> None:
    """Confirms det_score genuinely contributes to the combined score,
    not just that the output happens to be in range -- same image
    (identical blur/brightness), only det_score differs."""
    image = _real_image_bytes(fill=128)  # ideal brightness, deliberately
    bbox = [10, 10, 90, 90]

    low = InsightFaceQualityAssessor(app=_FakeApp([_FakeFace(bbox=bbox, det_score=0.0)]))
    high = InsightFaceQualityAssessor(app=_FakeApp([_FakeFace(bbox=bbox, det_score=1.0)]))

    low_result = await low.assess(image)
    high_result = await high.assess(image)

    assert low_result.quality_score is not None
    assert high_result.quality_score is not None
    assert high_result.quality_score > low_result.quality_score


@pytest.mark.asyncio
async def test_assess_crops_to_bbox_clipped_to_image_bounds() -> None:
    """A bbox extending past the image edge must not raise -- detector
    boxes can legitimately do this in practice."""
    fake = _FakeApp([_FakeFace(bbox=[-5, -5, 200, 200], det_score=0.7)])
    assessor = InsightFaceQualityAssessor(app=fake)
    result = await assessor.assess(_real_image_bytes())
    assert result.outcome is FaceQualityOutcome.VALID
    assert result.quality_score is not None
    assert 0.0 <= result.quality_score <= 1.0


@pytest.mark.asyncio
async def test_assess_raises_for_bbox_entirely_outside_image() -> None:
    """The failure chain this guards against: a bbox clipping to zero/
    negative width or height would otherwise slice to an EMPTY ndarray,
    which np.mean/cv2.Laplacian silently turn into NaN -- corrupting
    quality_score past its frozen [0.0, 1.0] contract. Must raise
    explicitly instead, never fabricate or NaN-derive a score. A bbox
    fully past the right/bottom edge of a 100x100 image is exactly this
    case after clipping (x1 clips to 100, same as x2 -> zero width)."""
    fake = _FakeApp([_FakeFace(bbox=[150, 150, 250, 250], det_score=0.9)])
    assessor = InsightFaceQualityAssessor(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await assessor.assess(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.QUALITY_DEGENERATE_CROP.value


@pytest.mark.asyncio
async def test_assess_raises_for_degenerate_zero_width_bbox() -> None:
    """A structurally degenerate bbox (x1 == x2) inside otherwise-valid
    image bounds -- not merely an edge-clipping case."""
    fake = _FakeApp([_FakeFace(bbox=[50, 10, 50, 90], det_score=0.9)])
    assessor = InsightFaceQualityAssessor(app=fake)
    with pytest.raises(CapabilityUnavailableError) as exc_info:
        await assessor.assess(_real_image_bytes())
    assert exc_info.value.reason_code == FaceReasonCode.QUALITY_DEGENERATE_CROP.value


@pytest.mark.asyncio
async def test_assess_clamps_out_of_range_det_score_before_combining() -> None:
    """Defensive vendor-boundary clamp: even a hypothetical det_score
    outside [0, 1] must not push quality_score outside its own frozen
    [0.0, 1.0] contract."""
    image = _real_image_bytes(fill=128)
    bbox = [10, 10, 90, 90]

    over_range = InsightFaceQualityAssessor(app=_FakeApp([_FakeFace(bbox=bbox, det_score=5.0)]))
    result = await over_range.assess(image)
    assert result.outcome is FaceQualityOutcome.VALID
    assert result.quality_score is not None
    assert 0.0 <= result.quality_score <= 1.0

    under_range = InsightFaceQualityAssessor(app=_FakeApp([_FakeFace(bbox=bbox, det_score=-3.0)]))
    result2 = await under_range.assess(image)
    assert result2.outcome is FaceQualityOutcome.VALID
    assert result2.quality_score is not None
    assert 0.0 <= result2.quality_score <= 1.0
