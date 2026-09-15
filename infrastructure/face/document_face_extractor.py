"""BD-001 Slice G (BD-001.2 D-1/D-2): the first real implementation of
`core.face.capabilities.DocumentFaceExtractor`. Deliberately independent
of `InsightFaceDetector` at the port level (BD-001.1 G-2) -- runs its
own `FaceAnalysis` detection call to obtain the bounding-box geometry
`FaceDetector`'s frozen contract never exposes (BD-001.1 G-1), the same
"any sharing of underlying detection work is strictly an
infrastructure-layer optimization, never a port-level coupling"
discipline `InsightFaceQualityAssessor`/`InsightFaceEmbedder` already
establish in `infrastructure/face/insightface_adapter.py`.

Nothing about InsightFace's own `Face` object (bbox included) is ever
visible past this module -- `extract_candidate()` reports only the
frozen `DocumentFaceExtractionResult` contract (an outcome plus,
iff VALID, already-cropped image bytes). The crop coordinates
themselves never cross this adapter's own boundary (BD-001.1 G-3).
"""

import asyncio

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from core.face.capabilities import CapabilityUnavailableError, DocumentFaceExtractor
from core.face.reason_codes import FaceReasonCode
from core.face.types import DocumentFaceExtractionOutcome, DocumentFaceExtractionResult

# JPEG re-encoding quality for the cropped face region -- a demo-only
# choice, not a calibrated compression setting. High enough that the
# crop stays usable input for the downstream FaceDetector/
# FaceQualityAssessor/FaceEmbedder sub-chain (Slice G.2), low enough to
# keep the resulting artifact reasonably small.
_JPEG_QUALITY = 95


class InsightFaceDocumentFaceExtractor(DocumentFaceExtractor):
    """Wraps a single, long-lived `FaceAnalysis` instance --
    `allowed_modules=["detection"]` only, the same minimal footprint
    `InsightFaceDetector`/`InsightFaceQualityAssessor` use, since the
    bbox this adapter needs comes from the detection module itself, no
    recognition needed."""

    def __init__(
        self,
        *,
        det_size: tuple[int, int] = (640, 640),
        app: FaceAnalysis | None = None,
    ) -> None:
        """`app`, if supplied, is used directly -- the same injection
        seam every InsightFace adapter in this project establishes, for
        hermetic unit tests and a future DI-wiring decision about
        instance sharing. Production call sites never pass it."""
        if app is not None:
            self._app = app
        else:
            self._app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection"],
            )
            self._app.prepare(ctx_id=-1, det_size=det_size)

    async def extract_candidate(self, image: bytes) -> DocumentFaceExtractionResult:
        image_array = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            return DocumentFaceExtractionResult(
                outcome=DocumentFaceExtractionOutcome.UNREADABLE, image=None
            )

        faces = await asyncio.to_thread(self._app.get, image_array)
        if len(faces) == 0:
            return DocumentFaceExtractionResult(
                outcome=DocumentFaceExtractionOutcome.NO_FACE, image=None
            )
        if len(faces) > 1:
            # No selection, ever -- BP Decision B-2's own boundary,
            # applied identically here: 2, 3, or 10 detected faces in a
            # document image all mean AMBIGUOUS.
            return DocumentFaceExtractionResult(
                outcome=DocumentFaceExtractionOutcome.AMBIGUOUS, image=None
            )

        face = faces[0]
        height, width = image_array.shape[:2]
        x1, y1, x2, y2 = face.bbox
        # Clip to image bounds -- the same defensive posture
        # InsightFaceQualityAssessor.assess() already establishes:
        # detector bboxes can extend slightly past the frame edge in
        # practice.
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(width, int(x2)), min(height, int(y2))
        if x2 <= x1 or y2 <= y1:
            # A bbox that clips to zero or negative width/height. Not a
            # normal NO_FACE/AMBIGUOUS outcome (a face WAS reported);
            # not an input-decodability problem either (the image
            # itself decoded fine) -- the detector's own output being
            # unusable for this operation, a genuine capability-level
            # anomaly, the same reasoning InsightFaceQualityAssessor's
            # own identical guard already documents in full.
            raise CapabilityUnavailableError(FaceReasonCode.EXTRACTION_DEGENERATE_CROP.value)

        cropped = image_array[y1:y2, x1:x2]
        encoded_ok, encoded = cv2.imencode(
            ".jpg", cropped, (cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY)
        )
        if not encoded_ok:
            # A successfully-decoded, non-degenerate crop that OpenCV's
            # own encoder still refuses -- no observed real-world
            # trigger for this, but cv2.imencode's own return contract
            # is a bool for exactly this reason and this adapter must
            # not silently trust it. A genuine capability-level anomaly,
            # not a face-count/decodability outcome -- same category as
            # the degenerate-crop guard above.
            raise CapabilityUnavailableError(FaceReasonCode.EXTRACTION_DEGENERATE_CROP.value)

        return DocumentFaceExtractionResult(
            outcome=DocumentFaceExtractionOutcome.VALID, image=bytes(encoded)
        )
