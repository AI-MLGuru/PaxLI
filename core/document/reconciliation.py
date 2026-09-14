"""DP-008 §5 / DP-009 §3: DocumentFieldReconciler is deliberately NOT
defined in core/document/capabilities.py. It shares that module's
domain-result discipline (never EvidenceResultStatus, never a
persistence identifier -- see capabilities.py's own module docstring)
but not its contract shape: every capabilities.py port is
`image: bytes -> domain result`; this is
`domain observations -> derived domain observation`. Forcing it into
the bytes-in port shape would misrepresent what that abstraction is for
in this codebase (an adapter seam for a future real implementation --
nothing about reconciliation will ever have one, DP-008 §5 point 3).

Synchronous, not async, unlike every capabilities.py port: this is pure
computation over already-fetched domain values, with no I/O of its own
-- honest about what it actually does, and consistent with there being
no CapabilityUnavailableError-shaped failure mode for it either (see
DocumentFieldReconciler's own docstring below).

This module defines the contract only (DP-009 §3) -- no implementation.
The deterministic stand-in (DP-009 §4) lives in
core.document.deterministic, mirroring every other capability's own
interface/implementation split.
"""

from abc import ABC, abstractmethod

from core.document.types import (
    BarcodeExtraction,
    FieldReconciliationResult,
    MRZExtraction,
    OCRExtraction,
)


class DocumentFieldReconciler(ABC):
    """No CapabilityUnavailableError analog: unlike OCR/MRZ/Barcode,
    there is no external model/dependency this can report as
    unavailable -- it is pure logic over inputs DocumentProcessor has
    already fetched. Any exception out of reconcile() is a programming
    defect, propagating uncaught exactly like every other unexpected
    exception in this pipeline (DP-002 reconciliation amendment B),
    never silently converted to an UNAVAILABLE result."""

    @abstractmethod
    def reconcile(
        self,
        *,
        ocr: OCRExtraction | None,
        mrz: MRZExtraction | None,
        barcode: BarcodeExtraction | None,
    ) -> FieldReconciliationResult:
        """Each parameter is None exactly when that source was ABSENT
        for this capture (DP-008 §3.7: NOT_SUBMITTED/UNAVAILABLE status,
        or for OCR, UNREADABLE) -- WHY a source is None is never encoded
        here; it stays reconstructible from that source's own persisted
        EvidenceResult via parent_evidence_result_ids (DP-008 §3.4/§5's
        interface-completeness resolution). A populated `mrz` is passed
        through regardless of whether MRZ's own EvidenceResultStatus was
        PASS or FAIL (DP-009 §7.1) -- this method never sees that status
        at all, by construction of its own signature, so it cannot
        special-case it even by accident.

        Always returns a populated result, never None --
        DOCUMENT_FIELD_EXTRACTION has no capability-level absence state
        of its own; if this method is called at all, all three inputs
        already went through DocumentProcessor's ambiguous-capture
        precondition."""
        raise NotImplementedError
