from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from core.evidence.models import Evidence, EvidenceTombstone


class EvidenceRepository(Protocol):
    async def add(self, evidence: Evidence, idempotency_key: str | None = None) -> Evidence: ...

    async def get_by_idempotency_key(
        self, tenant_id: str, session_id: UUID, idempotency_key: str
    ) -> Evidence | None: ...

    async def get(self, evidence_id: UUID, tenant_id: str) -> Evidence | None: ...

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> Sequence[Evidence]: ...

    async def list_expired(self, tenant_id: str, as_of: datetime) -> Sequence[Evidence]:
        """Evidence whose retention_until has passed and that has not
        already been requested for deletion (Invariant-06 remediation:
        retention eligibility, not automatic purge -- no scheduler acts on
        this list in v1)."""
        ...

    async def delete_content(self, evidence_id: UUID, tenant_id: str) -> bool:
        """Physical DELETE of the evidence row (Invariant-06 remediation
        decision: physical delete, not in-place nulling). Idempotent:
        returns True if a row was deleted, False if it was already absent
        -- callers use this to distinguish "deleted now" from "already
        satisfied" during reconciliation, never as an error."""
        ...

    async def add_tombstone(self, tombstone: EvidenceTombstone) -> EvidenceTombstone:
        """Phase-1 (request) persistence. Must be called at most once per
        evidence_id -- enforced by the tombstone table's primary key, not
        merely application logic."""
        ...

    async def get_tombstone(
        self, evidence_id: UUID, tenant_id: str
    ) -> EvidenceTombstone | None: ...

    async def mark_tombstone_executed(
        self, evidence_id: UUID, tenant_id: str, executed_at: datetime
    ) -> EvidenceTombstone:
        """Phase-2 (reconciliation) completion. Deliberately not a generic
        update() -- the only tombstone mutation this repository exposes."""
        ...
