"""BD-001 Slice B: the capability port replacing `core.face.provider`'s
rejected `FaceProvider` (BP-001 Decision 2 -- a monolithic ABC that
bundles detection/quality/embedding into one call, unable to express
independent per-stage failure/retry/supersession, the exact problem
DP-001 Decision 3 already solved for documents). Mirrors
`core.document.capabilities`'s own pattern deliberately: same
`CapabilityUnavailableError` shape, same `image: bytes -> domain result`
async contract -- BP-001 §7's own prediction confirmed as a clean fit,
not merely assumed.

Defined locally rather than imported from `core.document.capabilities`:
each domain owns its own capability-port module and its own
`CapabilityUnavailableError`, the same domain-separation discipline
`core/face/`, `core/document/`, `core/liveness/` already keep as
distinct packages -- a face capability raising a document-domain
exception type would be a cross-domain leak, not a reuse.
"""

from abc import ABC, abstractmethod

from core.face.types import (
    DocumentFaceExtractionResult,
    FaceDetection,
    FaceEmbedding,
    FaceQuality,
)


class CapabilityUnavailableError(Exception):
    """Raised by a capability implementation for a known, expected,
    self-diagnosed failure (model unavailable, timeout) that a future
    BiometricProcessor (BD-001 Slice G.2) would translate into a
    stage-level UNAVAILABLE EvidenceResult -- mirrors
    core.document.capabilities.CapabilityUnavailableError's own
    docstring and DP-002 reconciliation amendment exactly.

    Undecodable image bytes are explicitly NOT this: that is
    FaceDetectionOutcome.UNREADABLE, a legitimate domain result, not a
    capability/infrastructure failure (BD-001 Slice B's own
    reconciliation -- corrected from an earlier draft that proposed
    raising this exception for a "corrupt image the decoder rejects").
    Any OTHER exception -- a bug, an invariant violation, a
    configuration error -- is not this project's business to
    reinterpret as ordinary capability unavailability; it propagates
    uncaught."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class FaceDetector(ABC):
    @abstractmethod
    async def detect(self, image: bytes) -> FaceDetection:
        """Always returns a populated FaceDetection -- never None,
        mirroring OCREngine.extract()'s own non-optional contract.
        Cardinality (`face_count`) is reported as observed; this method
        MUST NOT apply any policy about whether a given cardinality is
        acceptable -- that is exclusively a future BiometricProcessor's
        concern (BD-001 Slice G.2, not yet built). In particular, this
        method never selects "the" face among several detected --
        it reports how many there are and nothing more."""
        raise NotImplementedError


class FaceQualityAssessor(ABC):
    """Deliberately has NO dependency on `FaceDetector` -- no import, no
    constructor parameter, nothing (DP-001 Decision 3's "independently
    addressable capability operations" principle, applied literally, the
    same as `QualityAssessor` never referencing `DocumentClassifier` on
    the document side). `FaceDetector.detect()`'s own return type
    (`FaceDetection`) couldn't serve this capability's needs anyway --
    it deliberately never exposes bbox/det_score, so depending on it
    wouldn't even work without leaking vendor shape into `core/`, the
    exact thing that boundary exists to prevent. Any sharing of
    underlying detection work between a `FaceDetector` and a
    `FaceQualityAssessor` implementation is strictly an
    infrastructure-layer optimization, decided at DI-wiring time
    (BD-001 Slice G), never a port-level coupling."""

    @abstractmethod
    async def assess(self, image: bytes) -> FaceQuality:
        """Always returns a populated FaceQuality -- never None, mirroring
        FaceDetector.detect()'s own non-optional contract. MUST NOT select
        a face among several candidates: `face_count == 1` is a structural
        precondition for producing a score at all (outcome=VALID);
        `face_count == 0` or `>= 2` both mean no score is produced
        (NO_FACE / AMBIGUOUS respectively) -- neither is a "poor quality"
        judgment, both are "no single quality-assessable subject exists."
        This method carries no opinion about whether NO_FACE/AMBIGUOUS
        should block verification -- that is exclusively a future
        BiometricProcessor's concern.

        May raise `CapabilityUnavailableError` for a detected face whose
        own reported region is unusable (e.g. a bounding box that clips
        to zero/negative width or height against the image) -- a genuine
        capability-level anomaly in the detector's own output, distinct
        from every `FaceQualityOutcome` member: a face WAS reported, so
        it isn't NO_FACE; there's exactly one, so it isn't AMBIGUOUS; the
        image itself decoded fine, so it isn't UNREADABLE. Never
        silently returns a fabricated or NaN-derived `quality_score` for
        this case."""
        raise NotImplementedError


class FaceEmbedder(ABC):
    """Deliberately independent of `FaceDetector`/`FaceQualityAssessor` at
    the port level -- same DP-001 Decision 3 boundary applied a third
    time. Any sharing of underlying detection/recognition work across
    implementations of these three capabilities is strictly an
    infrastructure-layer optimization, never a port-level coupling."""

    @abstractmethod
    async def embed(self, image: bytes) -> FaceEmbedding:
        """Always returns a populated FaceEmbedding -- never None,
        mirroring the other two face capabilities' non-optional contract.
        MUST NOT select a face among several candidates: `face_count == 1`
        is a structural precondition for producing an embedding at all
        (outcome=VALID); 0 or 2+ both mean no embedding is produced
        (NO_FACE / AMBIGUOUS) -- structural facts, not policy judgments.
        This method carries no opinion about whether NO_FACE/AMBIGUOUS
        should block verification, whether the embedding is "good enough"
        to match against, or which reference/probe pairing is being
        formed -- all exclusively a future BiometricProcessor's/
        FaceMatcher's concern.

        `outcome=VALID` is returned only once the embedding representation
        AND its model reference are both successfully established --
        never a partially-populated result. May raise
        `CapabilityUnavailableError` if the underlying representation
        fails validation (wrong dimensionality, non-finite values, a
        norm that isn't sufficiently close to unit length) -- the
        implementation MUST validate the vendor's own output rather than
        trusting it or silently repairing it (no re-normalization)."""
        raise NotImplementedError


class DocumentFaceExtractor(ABC):
    """BD-001.2 D-1: deliberately independent of `FaceDetector` at the
    port level -- `FaceDetector`'s frozen contract (BD-001.1 G-1) never
    exposes bounding-box geometry, and this capability needs exactly
    that to crop a document-bound reference artifact. Any real
    adapter's underlying vendor call may share the same technology
    `InsightFaceDetector` uses without sharing a domain-port dependency
    (BD-001.1 G-2) -- the same infrastructure-layer-optimization-only
    sharing discipline `FaceQualityAssessor`/`FaceEmbedder` already
    establish above, applied to a fourth, independently-motivated
    caller."""

    @abstractmethod
    async def extract_candidate(self, image: bytes) -> DocumentFaceExtractionResult:
        """Always returns a populated DocumentFaceExtractionResult --
        never None. MUST NOT select a face among several candidates:
        `face_count == 1` is a structural precondition for producing a
        crop at all (outcome=VALID); 0 or 2+ both mean no crop is
        produced (NO_FACE / AMBIGUOUS) -- structural facts, the same
        BP Decision B-2 boundary every other face capability enforces.
        This method carries no opinion about whether the resulting
        artifact is "good enough" to embed or match -- exclusively a
        future BiometricProcessor's/FaceEmbedder's/FaceMatcher's
        concern.

        May raise `CapabilityUnavailableError` for a genuine
        InsightFace/ONNX Runtime failure -- never for undecodable image
        bytes (that is `DocumentFaceExtractionOutcome.UNREADABLE`, a
        legitimate domain result, not a capability/infrastructure
        failure -- BD-001.1 G-3's frozen boundary: bad input is never
        represented as provider unavailability)."""
        raise NotImplementedError
