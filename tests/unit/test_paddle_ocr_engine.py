"""BD-001 Slice A: PaddleOCREngine's own decode/translation logic,
exercised via the `ocr=` injection seam so this stays a fast, hermetic
unit test -- it never constructs a real PaddleOCR pipeline (that would
mean a real, multi-second model load, and a network call on first run,
neither appropriate for this project's normal test suite). Real,
end-to-end PaddleOCR behavior was confirmed live once, manually, against
the actual installed model (see infrastructure/document/paddle_ocr_engine.py's
own docstring for what was observed) -- this file tests only the
adapter's own mapping logic, not PaddleOCR itself.
"""

from typing import Any

import cv2
import numpy as np
import pytest

from core.document.types import OCRReadOutcome
from infrastructure.document.paddle_ocr_engine import PaddleOCREngine


def _real_png_bytes() -> bytes:
    """A genuinely valid, decodable PNG -- PaddleOCREngine.extract() calls
    cv2.imdecode() for real, so a bare magic-number fragment (as other
    capability tests in this project use for their own, non-decoding
    stand-ins) would not exercise the real decode path honestly."""
    array = np.full((20, 20, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", array)
    assert ok
    return bytes(encoded)


class _FakeResult:
    def __init__(self, rec_texts: list[str]) -> None:
        self.json: dict[str, Any] = {"res": {"rec_texts": rec_texts}}


class _FakeOCR:
    """Matches only the single method PaddleOCREngine.extract() actually
    calls -- deliberately not a full PaddleOCR stand-in."""

    def __init__(self, rec_texts: list[str]) -> None:
        self._rec_texts = rec_texts
        self.received: Any = None
        self.call_count = 0

    def predict(self, input: Any) -> list[_FakeResult]:
        self.call_count += 1
        self.received = input
        return [_FakeResult(self._rec_texts)]


@pytest.mark.asyncio
async def test_extract_reports_unreadable_when_no_text_recognized() -> None:
    engine = PaddleOCREngine(ocr=_FakeOCR([]))
    result = await engine.extract(_real_png_bytes())
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_extract_reports_unreadable_for_undecodable_bytes_without_calling_predict() -> None:
    """Reachable in production, not hypothetical: core/evidence/
    media_validation.py verifies only the file signature, not full
    decodability -- a corrupted-but-correctly-signed upload reaches this
    adapter as real bytes. cv2.imdecode() returning None must map to
    OCREngine's own UNREADABLE contract, never reach PaddleOCR.predict()
    with None (which would fail with an opaque, unrelated exception)."""
    fake = _FakeOCR(["should never be reached"])
    engine = PaddleOCREngine(ocr=fake)
    result = await engine.extract(b"not an image at all, just random bytes")
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None
    assert fake.call_count == 0  # predict() was never called


@pytest.mark.asyncio
async def test_extract_reports_valid_and_joins_recognized_lines() -> None:
    fake = _FakeOCR(["FEDERAL REPUBLIC OF NIGERIA", "PASSPORT"])
    engine = PaddleOCREngine(ocr=fake)
    result = await engine.extract(_real_png_bytes())
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == "FEDERAL REPUBLIC OF NIGERIA\nPASSPORT"


@pytest.mark.asyncio
async def test_extract_fields_are_always_empty() -> None:
    """core/document/types.py's own contract: OCRExtraction.fields is
    source-specific and non-canonical -- a real OCR engine has no
    inherent key-value structure to offer, unlike DeterministicOCREngine's
    synthetic test-fixture parser (DP-005 Decision 7)."""
    engine = PaddleOCREngine(ocr=_FakeOCR(["some recognized text"]))
    result = await engine.extract(_real_png_bytes())
    assert result.extraction is not None
    assert result.extraction.fields == {}


@pytest.mark.asyncio
async def test_extract_decodes_bytes_before_calling_predict() -> None:
    """Confirms the adapter passes a decoded ndarray to PaddleOCR, never
    raw bytes -- PaddleOCR/PaddleX's own input contract is an image
    array/path, not an encoded byte string."""
    fake = _FakeOCR(["text"])
    engine = PaddleOCREngine(ocr=fake)
    await engine.extract(_real_png_bytes())
    assert isinstance(fake.received, np.ndarray)
    assert fake.received.shape == (20, 20, 3)
