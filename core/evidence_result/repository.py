from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from core.evidence_result.enums import EvidenceResultType
from core.evidence_result.models import EvidenceResult, EvidenceResultTombstone


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

    async def list_effective_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]:
        """DE-003 §2/§11: only non-superseded (is_effective=true) results --
        the query-time filter the Decision Engine's effective-evidence
        resolver depends on. At most one row per evidence_type is possible
        here when ix_evidence_results_one_effective_per_type holds."""
        ...

    async def list_effective_for_session_by_type(
        self, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> Sequence[EvidenceResult]: ...

    async def mark_not_effective(self, evidence_result_id: UUID, tenant_id: str) -> None:
        """Narrow transition: flips is_effective to False on an existing
        row. Deliberately not a generic update() -- the only mutation this
        method performs. Called by supersede() on the row being superseded,
        in the same transaction as the new row's insert, so the partial
        unique index never observes two effective rows for the same type
        even momentarily."""
        ...

    async def list_expired(self, tenant_id: str, as_of: datetime) -> Sequence[EvidenceResult]:
        """Evidence results whose retention_until has passed and that have
        not already been requested for deletion (Invariant-06 remediation:
        retention eligibility, not automatic purge -- no scheduler acts on
        this list in v1)."""
        ...

    async def has_dependent_evidence_results(
        self, evidence_result_id: UUID, tenant_id: str
    ) -> bool:
        """True if any other EvidenceResult.supersedes_id still points at
        this evidence_result_id -- same root cause and rationale as
        EvidenceRepository.has_dependent_evidence_results (Invariant-06
        remediation Phase 6 finding), applied to the self-referencing
        supersedes_id foreign key."""
        ...

    async def delete_content(self, evidence_result_id: UUID, tenant_id: str) -> bool:
        """Physical DELETE of the evidence_results row. Idempotent: returns
        True if a row was deleted, False if it was already absent."""
        ...

    async def add_tombstone(
        self, tombstone: EvidenceResultTombstone
    ) -> EvidenceResultTombstone:
        """Phase-1 (request) persistence. Must be called at most once per
        evidence_result_id -- enforced by the tombstone table's primary
        key, not merely application logic."""
        ...

    async def get_tombstone(
        self, evidence_result_id: UUID, tenant_id: str
    ) -> EvidenceResultTombstone | None: ...

    async def mark_tombstone_executed(
        self, evidence_result_id: UUID, tenant_id: str, executed_at: datetime
    ) -> EvidenceResultTombstone:
        """Phase-2 (reconciliation) completion. Deliberately not a generic
        update() -- the only tombstone mutation this repository exposes."""
        ...
