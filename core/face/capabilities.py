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

from core.face.types import FaceDetection


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
