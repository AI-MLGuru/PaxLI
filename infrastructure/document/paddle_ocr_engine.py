"""BD-001 Slice A: the first real (non-stand-in) `core.document.capabilities`
implementation. Translates PaddleOCR's own response shape into
`OCRReadResult`/`OCRExtraction` -- nothing about PaddleOCR's result object,
config surface, or model names is ever visible past this module (per the
explicit instruction not to let PaddleOCR's shape leak into
`core/document`).

`fields: dict[str, str]` is always empty here, deliberately -- unlike
`DeterministicOCREngine`'s synthetic `key=value;` fixture parser (a
test-only convenience with no real-world analog), real recognized text
has no inherent key-value structure. `OCRExtraction.fields` is documented
as "source-specific, non-canonical" (core/document/types.py) precisely so
each source may leave it empty; canonical field extraction is Phase 4's
job (DocumentFieldReconciler), never OCREngine's own.

No `CapabilityUnavailableError` handling is added here. This mirrors
`DeterministicOCREngine`'s own lack of any exception handling, and the
DP-002 reconciliation amendment's own rule: only a known, expected,
self-diagnosed failure mode may be caught and translated -- inventing a
speculative catch for a PaddleOCR/PaddleX failure this adapter has never
actually observed would misrepresent an unexamined exception as an
anticipated one. If a real, observed failure mode needs graceful
handling later, it gets added then, grounded in what was actually seen.
"""

import asyncio
import os

# MUST be set before paddleocr/paddlex is first imported anywhere in this
# process -- paddlex.utils.flags.ENABLE_MKLDNN_BYDEFAULT is a module-level
# constant read once at import time from this exact env var. Not a
# defensive guess: this works around a real, reproduced failure on this
# project's own dev machine -- PaddlePaddle 3.3.1's oneDNN CPU execution
# path raised `NotImplementedError: (Unimplemented)
# ConvertPirAttribute2RuntimeAttribute not support
# [pir::ArrayAttribute<pir::DoubleAttribute>]` loading PP-OCRv6's detection
# model, and disabling oneDNN (falling back to PaddlePaddle's plain CPU
# executor) was the confirmed fix, not a hypothetical one.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from paddleocr import PaddleOCR  # noqa: E402

from core.document.capabilities import OCREngine
from core.document.types import OCRExtraction, OCRReadOutcome, OCRReadResult


class PaddleOCREngine(OCREngine):
    """Wraps a single, long-lived `PaddleOCR` pipeline instance -- model
    load is expensive (the underlying detection+recognition models are
    loaded once at construction) and MUST NOT happen per-request, the
    same discipline BD-001 Slice B applies to `InsightFaceDetector`.

    `lang`/orientation-classification/unwarping are constructor
    parameters, not hardcoded, because BD-001 Slice A explicitly leaves
    the exact model/language-pack selection to empirical benchmarking
    against real document samples, not to this file. The defaults below
    are the minimal configuration confirmed working on this project's
    own dev machine (detection + recognition only, no document
    orientation/unwarping preprocessing) -- a starting point, not a
    frozen production choice.
    """

    def __init__(
        self,
        *,
        lang: str = "en",
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_textline_orientation: bool = False,
        ocr: PaddleOCR | None = None,
    ) -> None:
        """`ocr`, if supplied, is used directly instead of constructing a
        real `PaddleOCR` pipeline -- the seam unit tests use to exercise
        `extract()`'s own decode/translation logic without paying a real
        model's multi-second load cost. Production call sites never pass
        it; every real construction goes through the module-level
        singleton (apps.api.paxli_api.dependencies._get_paddle_ocr_engine),
        never this parameter."""
        self._ocr = ocr if ocr is not None else PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=use_doc_orientation_classify,
            use_doc_unwarping=use_doc_unwarping,
            use_textline_orientation=use_textline_orientation,
        )

    async def extract(self, image: bytes) -> OCRReadResult:
        image_array = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image_array is None:
            # Reachable in production, not merely hypothetical:
            # core/evidence/media_validation.py verifies only the file
            # SIGNATURE (its own docstring: "signature verification, not
            # content/malware scanning") before storage -- a
            # correctly-signed but truncated/corrupted JPEG/PNG/WEBP
            # passes that check and reaches this adapter as real bytes.
            # OCREngine.extract()'s own contract (core/document/
            # capabilities.py) already answers this: "inability to
            # recognize usable text is the outcome UNREADABLE, never an
            # absence of applicability" -- undecodable bytes are exactly
            # that, not a capability/infrastructure failure
            # (CapabilityUnavailableError's own domain), and not a
            # CapabilityUnavailableError-worthy "malformed input" either
            # -- OCR has no MALFORMED outcome at all (DP-005 Decision 2:
            # "no structural grammar to violate"), only UNREADABLE/VALID.
            # This maps onto the already-existing, already-tested
            # _OCR_OUTCOME_MAP (infrastructure/document/processor.py) ->
            # EvidenceResultStatus.INCONCLUSIVE, zero DocumentProcessor
            # changes needed.
            return OCRReadResult(outcome=OCRReadOutcome.UNREADABLE, extraction=None)
        results = await asyncio.to_thread(self._ocr.predict, image_array)
        # `predict()` returns one result per input page; this adapter is
        # only ever called with a single decoded image, so exactly one
        # result is expected here -- confirmed directly (probed live
        # against PaddleOCR 3.7.0), not assumed from documentation.
        page = results[0].json["res"]
        texts: list[str] = page["rec_texts"]
        if not texts:
            return OCRReadResult(outcome=OCRReadOutcome.UNREADABLE, extraction=None)
        return OCRReadResult(
            outcome=OCRReadOutcome.VALID,
            extraction=OCRExtraction(raw="\n".join(texts), fields={}),
        )
