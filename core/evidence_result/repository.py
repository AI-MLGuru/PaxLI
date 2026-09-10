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

    async def add(self, evidence_result: EvidenceResult) -> EvidenceResult: ...

    async def get(self, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None: ...

    async def list_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]: ...

    async def list_for_session_by_type(
        self, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> Sequence[EvidenceResult]: ...
