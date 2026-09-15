"""BD-001 Slice B: the first real (non-stand-in) `core.face.capabilities`
implementation. TD-001's frozen technology choice (InsightFace
`buffalo_l`, ONNX Runtime CPU) applied to detection only -- recognition
(embedding) is Slice D's own future adapter, not built here.

Nothing about InsightFace's own `Face` object (bbox, det_score, kps,
embedding) is ever visible past this module -- this adapter reports
only `detected`/`face_count`, exactly the frozen `FaceDetection`
contract, the same "don't let the vendor SDK's shape leak into core/"
discipline `PaddleOCREngine` already established for OCR.
"""

import asyncio

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from core.face.capabilities import FaceDetector
from core.face.types import FaceDetection, FaceDetectionOutcome


class InsightFaceDetector(FaceDetector):
    """Wraps a single, long-lived `FaceAnalysis` instance -- model load
    is expensive (TD-001 measured 6-18s depending on configuration) and
    MUST NOT happen per request, the same discipline
    `infrastructure.document.paddle_ocr_engine.PaddleOCREngine` already
    established.

    `allowed_modules=["detection"]` only -- Slice B needs no recognition
    model (that's Slice D's own adapter, not yet built). Whether a
    future embedder shares this exact `FaceAnalysis` instance, adds
    "recognition" to this same instance, or constructs its own is
    explicitly NOT decided here (BD-001 Slice B: "internal session
    topology... subject to measurement," per TD-001's own
    counter-intuitive restricted-module benchmark result) -- this
    adapter is deliberately minimal for what Slice B alone needs.
    """

    def __init__(
        self,
        *,
        det_size: tuple[int, int] = (640, 640),
        app: FaceAnalysis | None = None,
    ) -> None:
        """`app`, if supplied, is used directly instead of constructing a
        real `FaceAnalysis` pipeline -- the seam unit tests use to
        exercise `detect()`'s own decode/translation logic without
        paying a real model's multi-second load cost, the same pattern
        `PaddleOCREngine`'s `ocr=` parameter already established.
        Production call sites never pass it."""
        if app is not None:
            self._app = app
        else:
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection"],
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)

    async def detect(self, image: bytes) -> FaceDetection:
        image_array = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            # Same reasoning PaddleOCREngine already documents in full:
            # core/evidence/media_validation.py verifies only the file
            # signature, not full decodability, so a corrupted-but-
            # correctly-signed upload reaching this adapter as real
            # bytes is reachable in production, not hypothetical.
            # BD-001 Slice B (this reconciliation pass) corrects an
            # earlier draft that proposed CapabilityUnavailableError
            # here -- undecodable bytes are FaceDetectionOutcome's own
            # UNREADABLE outcome, not a capability/infrastructure
            # failure.
            return FaceDetection(
                outcome=FaceDetectionOutcome.UNREADABLE, detected=None, face_count=None
            )
        faces = await asyncio.to_thread(self._app.get, image_array)
        return FaceDetection(
            outcome=FaceDetectionOutcome.VALID,
            detected=len(faces) > 0,
            face_count=len(faces),
        )
