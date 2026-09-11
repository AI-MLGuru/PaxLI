from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from core.evidence_result.enums import EvidenceResultType
from core.evidence_result.models import EvidenceResult


class EvidenceResultRepository(Protocol):
    """No update() -- immutability (EVD-3.10, Invariant 06 §6.1/6.6) is
    structural, not conventional. A superseding result is a new row
    (EvidenceResultService.supersede()), never a mutation of an existing one.
    """

    async def add(
        self, evidence_result: EvidenceResult, idempotency_key: str | None = None
    ) -> EvidenceResult: ...

    async def get_by_idempotency_key(
        self, tenant_id: str, session_id: UUID, idempotency_key: str
    ) -> EvidenceResult | None:
        """`idempotency_key` here is the composed, operation-scoped key
        (e.g. "evidence_result_create:<caller-key>") -- see
        core.evidence_result.service for composition (Invariant-12
        remediation review: idempotency must be operation-scoped, not
        merely tenant-scoped)."""
        ...

    async def get(self, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None: ...

    async def list_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]: ...

    async def list_for_session_by_type(
        self, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> Sequence[EvidenceResult]: ...
