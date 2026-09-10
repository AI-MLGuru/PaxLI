import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult, ModelReference
from core.evidence_result.repository import EvidenceResultRepository
from core.evidence_result.schemas import validate_result_payload

_SYSTEM_ACTOR_ID = "evidence-result-service"


def _compute_integrity_reference(
    *,
    evidence_type: EvidenceResultType,
    status: EvidenceResultStatus,
    result: dict[str, Any] | None,
    producer: str,
    producer_version: str,
) -> str:
    canonical = json.dumps(
        {
            "evidence_type": evidence_type.value,
            "status": status.value,
            "result": result,
            "producer": producer,
            "producer_version": producer_version,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvidenceResultService:
    """Domain service for Part III evidence results.

    Has no awareness of encryption: `result` is always a plain dict here.
    Whether and how a given evidence_type's payload is protected at rest is
    decided by the repository implementation (infrastructure layer), keyed
    off core.evidence_result.classification.classify() -- this service
    never imports core.security.keys or calls encrypt/decrypt.
    """

    def __init__(self, repository: EvidenceResultRepository, audit_service: AuditService) -> None:
        self.repository = repository
        self.audit_service = audit_service

    async def create(
        self,
        *,
        tenant_id: str,
        session_id: UUID,
        evidence_type: EvidenceResultType,
        status: EvidenceResultStatus,
        producer: str,
        producer_version: str,
        result: dict[str, Any] | None = None,
        reason_codes: tuple[str, ...] = (),
        score: float | None = None,
        quality: float | None = None,
        model_reference: ModelReference | None = None,
        source_reference: UUID | None = None,
        parent_evidence_result_ids: tuple[UUID, ...] = (),
        retention_until: datetime | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResult:
        """Raises InvalidEvidenceResultError (via validate_result_payload)
        before anything is persisted -- the caller is responsible for
        recovering with a safe INCONCLUSIVE result of its own (EVD-3.24.3);
        this method does not auto-substitute one."""
        validate_result_payload(evidence_type, result)

        now = datetime.now(UTC)
        evidence_result = EvidenceResult(
            id=uuid4(),
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=evidence_type,
            status=status,
            result=result,
            reason_codes=reason_codes,
            score=score,
            quality=quality,
            producer=producer,
            producer_version=producer_version,
            model_reference=model_reference,
            source_reference=source_reference,
            parent_evidence_result_ids=parent_evidence_result_ids,
            produced_at=now,
            persisted_at=now,
            integrity_reference=_compute_integrity_reference(
                evidence_type=evidence_type,
                status=status,
                result=result,
                producer=producer,
                producer_version=producer_version,
            ),
            retention_until=retention_until,
        )
        saved = await self.repository.add(evidence_result)
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=AuditEventType.EVIDENCE_RESULT_CREATED,
            component="evidence_result",
            action="create",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "evidence_result_id": str(saved.id),
                "evidence_type": evidence_type.value,
                "status": status.value,
                "producer": producer,
            },
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def supersede(
        self,
        *,
        evidence_result_id: UUID,
        tenant_id: str,
        session_id: UUID,
        evidence_type: EvidenceResultType,
        status: EvidenceResultStatus,
        producer: str,
        producer_version: str,
        result: dict[str, Any] | None = None,
        reason_codes: tuple[str, ...] = (),
        score: float | None = None,
        quality: float | None = None,
        model_reference: ModelReference | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> EvidenceResult:
        """Creates a NEW evidence result that supersedes an existing one
        (EVD-3.10.3) -- never mutates the original row."""
        validate_result_payload(evidence_type, result)

        now = datetime.now(UTC)
        evidence_result = EvidenceResult(
            id=uuid4(),
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=evidence_type,
            status=status,
            result=result,
            reason_codes=reason_codes,
            score=score,
            quality=quality,
            producer=producer,
            producer_version=producer_version,
            model_reference=model_reference,
            supersedes_id=evidence_result_id,
            produced_at=now,
            persisted_at=now,
            integrity_reference=_compute_integrity_reference(
                evidence_type=evidence_type,
                status=status,
                result=result,
                producer=producer,
                producer_version=producer_version,
            ),
        )
        saved = await self.repository.add(evidence_result)
        await self.audit_service.record(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=AuditEventType.EVIDENCE_RESULT_SUPERSEDED,
            component="evidence_result",
            action="supersede",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR_ID,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "evidence_result_id": str(saved.id),
                "supersedes_id": str(evidence_result_id),
                "evidence_type": evidence_type.value,
                "status": status.value,
            },
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def get(self, *, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None:
        return await self.repository.get(evidence_result_id, tenant_id)

    async def list_for_session(
        self, *, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]:
        return await self.repository.list_for_session(session_id, tenant_id)
