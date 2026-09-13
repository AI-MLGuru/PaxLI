"""DP-001 Decision 3: independently replaceable capability ports.

Each capability returns a domain result (core.document.types), never an
EvidenceResult -- core.document.processor's DocumentProcessor alone owns
translating a capability's output into persisted, lineage-bearing
EvidenceResult rows. A capability MUST NOT be passed persistence
identifiers (e.g. a classification EvidenceResult's row ID) -- only the
domain-level value it needs (e.g. a plain document_type string/enum
member for AuthenticityChecker, if that capability is ever built).

QualityAssessor, DocumentClassifier (Phase 1), MRZParser, and
BarcodeDecoder (Phase 2, DP-003/DP-004) have deterministic
implementations (core.document.deterministic). OCREngine remains
interface-only -- DP-003 Decision 11 keeps OCR and DOCUMENT_FIELD_
EXTRACTION reconciliation out of scope pending a future phase.

Where a capability's own return type is Optional (MRZParser, BarcodeDecoder):
None means the capability found no applicable input/presence to
process; it is a legitimate outcome and never represents failure.
Capabilities whose domain necessarily applies to every submitted
capture (QualityAssessor, DocumentClassifier) need not use an optional
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
    OCRExtraction,
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
    """No Phase 1 implementation -- interface only (DP-001 Decision 3)."""

    @abstractmethod
    async def extract(self, image: bytes) -> OCRExtraction:
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
