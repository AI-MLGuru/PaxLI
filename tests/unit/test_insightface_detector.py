"""BD-001 Slice B: InsightFaceDetector's own decode/translation logic,
exercised via the `app=` injection seam so this stays a fast, hermetic
unit test -- it never constructs a real FaceAnalysis pipeline (a real,
multi-second model load). Real, end-to-end InsightFace detection was
confirmed live, manually, against the actual installed buffalo_l model
(detection-only module configuration) before this adapter was written.
"""

from typing import Any

import cv2
import numpy as np
import pytest

from core.face.types import FaceDetectionOutcome
from infrastructure.face.insightface_adapter import InsightFaceDetector


def _real_jpeg_bytes() -> bytes:
    """A genuinely valid, decodable image -- detect() calls cv2.imdecode()
    for real, so a bare magic-number fragment would not exercise the
    real decode path honestly."""
    array = np.full((20, 20, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", array)
    assert ok
    return bytes(encoded)


class _FakeApp:
    """Matches only the single method InsightFaceDetector.detect()
    actually calls -- deliberately not a full FaceAnalysis stand-in."""

    def __init__(self, faces: list[object]) -> None:
        self._faces = faces
        self.call_count = 0
        self.received: Any = None

    def get(self, image: Any) -> list[object]:
        self.call_count += 1
        self.received = image
        return self._faces


@pytest.mark.asyncio
async def test_detect_reports_unreadable_for_undecodable_bytes_without_calling_get() -> None:
    """Reachable in production, not hypothetical -- same reasoning
    PaddleOCREngine's own equivalent test documents: core/evidence/
    media_validation.py verifies only the file signature, not full
    decodability."""
    fake = _FakeApp([object()])  # would prove non-empty if reached
    detector = InsightFaceDetector(app=fake)
    result = await detector.detect(b"not an image at all, just random bytes")
    assert result.outcome is FaceDetectionOutcome.UNREADABLE
    assert result.detected is None
    assert result.face_count is None
    assert fake.call_count == 0  # app.get() was never called


@pytest.mark.asyncio
async def test_detect_reports_valid_with_zero_faces() -> None:
    """VALID + face_count=0 is a legitimate, fully successful result --
    the image was examined and no face is present. Not UNREADABLE."""
    detector = InsightFaceDetector(app=_FakeApp([]))
    result = await detector.detect(_real_jpeg_bytes())
    assert result.outcome is FaceDetectionOutcome.VALID
    assert result.detected is False
    assert result.face_count == 0


@pytest.mark.asyncio
async def test_detect_reports_valid_with_one_face() -> None:
    detector = InsightFaceDetector(app=_FakeApp([object()]))
    result = await detector.detect(_real_jpeg_bytes())
    assert result.outcome is FaceDetectionOutcome.VALID
    assert result.detected is True
    assert result.face_count == 1


@pytest.mark.asyncio
async def test_detect_reports_raw_cardinality_for_multiple_faces_without_selecting_one() -> None:
    """B-2: FaceDetector reports cardinality only -- it must never select
    "the" face among several. This test asserts the raw count is
    reported faithfully; it deliberately does NOT assert anything about
    which face was "chosen," because none is -- that would be exactly
    the heuristic BD-001 Slice G.2 explicitly forbids here."""
    detector = InsightFaceDetector(app=_FakeApp([object(), object(), object()]))
    result = await detector.detect(_real_jpeg_bytes())
    assert result.outcome is FaceDetectionOutcome.VALID
    assert result.detected is True
    assert result.face_count == 3


@pytest.mark.asyncio
async def test_detect_decodes_bytes_before_calling_get() -> None:
    """Confirms the adapter passes a decoded ndarray to InsightFace,
    never raw bytes."""
    fake = _FakeApp([object()])
    detector = InsightFaceDetector(app=fake)
    await detector.detect(_real_jpeg_bytes())
    assert isinstance(fake.received, np.ndarray)
    assert fake.received.shape == (20, 20, 3)
