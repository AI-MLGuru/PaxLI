"""BD-001 Slice I (BD-001.10/BD-001.11): the dependency-inversion
boundary between `core.verification.workflow`'s `VerificationWorkflowService`
and the real `BiometricProcessor` implementation
(`infrastructure.face.processor.BiometricProcessor`) -- mirrors
`core.document.processor.DocumentProcessor`'s own Protocol exactly, for
the same reason: `core/` depends only on this narrow Protocol, never on
`infrastructure/` directly, so the concrete class stays free to open
its own database sessions, own SQLAlchemy dependencies, etc. without
`core/verification/` ever needing to know that.

Defined as a Protocol, not a concrete class, matching `DocumentProcessor`'s
own precedent -- structural typing means `infrastructure.face.processor.BiometricProcessor`
satisfies this without importing it or inheriting from it.
"""

from typing import Protocol
from uuid import UUID


class BiometricProcessor(Protocol):
    async def process(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Called unconditionally from VerificationWorkflowService.submit()'s
        PROCESSING branch, after document_processor.process() and before
        decision_orchestrator.evaluate_and_persist() (BD-001.10 §4's
        frozen ordering -- the reference side depends on
        DOCUMENT_FIELD_EXTRACTION already being effective). No-ops
        internally when no reference can be acquired and no SELFIE
        capture exists (BD-001.7 G.2-S1/G.2-S11) -- absence is the
        Decision Engine's concern, not this method's."""
        ...
