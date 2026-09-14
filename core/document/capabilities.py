"""DP-001 Decision 3: independently replaceable capability ports.

Each capability returns a domain result (core.document.types), never an
EvidenceResult -- core.document.processor's DocumentProcessor alone owns
translating a capability's output into persisted, lineage-bearing
EvidenceResult rows. A capability MUST NOT be passed persistence
identifiers (e.g. a classification EvidenceResult's row ID) -- only the
domain-level value it needs (e.g. a plain document_type string/enum
member for AuthenticityChecker, if that capability is ever built).

QualityAssessor, DocumentClassifier (Phase 1), MRZParser, BarcodeDecoder
(Phase 2, DP-003/DP-004), and OCREngine (Phase 3, DP-005/DP-006) all
have deterministic implementations (core.document.deterministic).
DOCUMENT_FIELD_EXTRACTION reconciliation (Phase 4, DP-008/DP-009) is
deliberately NOT a port defined here -- it does not share this module's
`image: bytes -> domain result` contract shape (its inputs are other
capabilities' own domain results, not image bytes) and has no plausible
future real adapter to justify the "swappable behind a port" pattern
this module exists for. See core.document.reconciliation.DocumentFieldReconciler
instead.

Where a capability's own return type is Optional (MRZParser, BarcodeDecoder):
None means the capability found no applicable input/presence to
process; it is a legitimate outcome and never represents failure.
Capabilities whose domain necessarily applies to every submitted
capture (QualityAssessor, DocumentClassifier, and -- for a different
reason, DP-005 Decision 3 -- OCREngine) need not use an optional
return.

AuthenticityChecker is deliberately NOT defined here at all. DP-001
Decision 6 found no defensible V1 authenticity signal exists outside
what Part IX §9.15 explicitly defers -- there is nothing for a port to
serve yet, and defining an interface with no planned caller and no
planned implementation is speculative surface area this project's own
discipline argues against.
"""

from abc import ABC, abstractmethod

from core.document.types import (
    BarcodeReadResult,
    DocumentClassification,
    MRZReadResult,
    OCRReadResult,
    QualityAssessment,
)


class CapabilityUnavailableError(Exception):
    """Raised by a capability implementation for a known, expected,
    self-diagnosed failure (model unavailable, timeout, recognized
    malformed input) that DocumentProcessor translates into a
    stage-level UNAVAILABLE EvidenceResult. Capabilities MUST NOT use
    this for anything they cannot positively identify as an expected
    failure mode.

    Any OTHER exception -- a bug, an invariant violation, a
    configuration error -- is not this project's business to
    reinterpret as ordinary capability unavailability (DP-002
    reconciliation amendment, closing exactly the failure mode HV-006
    already established this project must not hide): it propagates
    uncaught out of DocumentProcessor, reaches the existing WF-006
    catch-all, and surfaces as a logged, observable 500 -- never
    silently normalized."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class QualityAssessor(ABC):
    @abstractmethod
    async def assess(self, image: bytes) -> QualityAssessment:
        raise NotImplementedError


class DocumentClassifier(ABC):
    @abstractmethod
    async def classify(self, image: bytes) -> DocumentClassification:
        raise NotImplementedError


class OCREngine(ABC):
    """DP-005/DP-006 Phase 3."""

    @abstractmethod
    async def extract(self, image: bytes) -> OCRReadResult:
        """Always returns a populated OCRReadResult -- never None (DP-005
        Decision 3). OCR has no capability-level absence/not-applicable
        state: whenever this method is actually called, inability to
        recognize usable text is the outcome UNREADABLE, never an
        absence of applicability. This says nothing about WHETHER the
        capability gets called for a given capture -- DocumentProcessor's
        existing ambiguous-capture precondition still short-circuits
        BEFORE any capability invocation, exactly as it already does for
        every other stage; that is pipeline-level precondition handling,
        not a capability-level absence state, and Decision 3 does not
        touch it."""
        raise NotImplementedError


class MRZParser(ABC):
    """DP-003/DP-004 Phase 2."""

    @abstractmethod
    async def parse(self, image: bytes) -> MRZReadResult | None:
        """None = no MRZ zone present at all -> MRZ=NOT_SUBMITTED. A
        populated MRZReadResult explicitly states what happened
        attempting to read/parse/validate whatever zone was found --
        DocumentProcessor never infers this from extraction's shape."""
        raise NotImplementedError


class BarcodeDecoder(ABC):
    """DP-003/DP-004 Phase 2."""

    @abstractmethod
    async def decode(self, image: bytes) -> BarcodeReadResult | None:
        """None = no barcode/QR symbol present at all -> BARCODE_QR=NOT_SUBMITTED."""
        raise NotImplementedError
