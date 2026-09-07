from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.models import Evidence
from core.evidence.repository import EvidenceRepository
from core.verification.service import SessionExpiredError, VerificationSessionService

if TYPE_CHECKING:
    from infrastructure.storage.interface import ObjectStorage


class EvidenceService:
    def __init__(
        self,
        repository: EvidenceRepository,
        session_service: VerificationSessionService,
        storage: "ObjectStorage",
        retention_days: int = 30,
    ) -> None:
        self.repository = repository
        self.session_service = session_service
        self.storage = storage
        self.retention_days = retention_days

    async def add(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        evidence_type: EvidenceType,
        content: bytes,
        mime_type: str,
        checksum: str,
        metadata: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Evidence:
        session = await self.session_service.get(session_id=session_id, tenant_id=tenant_id)
        if session.status.value in {"EXPIRED", "CANCELLED"}:
            raise SessionExpiredError
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(
                tenant_id, session_id, idempotency_key
            )
            if existing is not None:
                return existing

        object_key = f"{tenant_id}/{session_id}/{evidence_type.value.lower()}/{checksum}"
        await self.storage.put(object_key, content, mime_type)
        evidence = Evidence(
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=evidence_type,
            source=EvidenceSource.CLIENT,
            object_key=object_key,
            checksum=checksum,
            mime_type=mime_type,
            size_bytes=len(content),
            metadata=metadata,
            retention_until=session.created_at + timedelta(days=self.retention_days),
        )
        try:
            return await self.repository.add(evidence, idempotency_key)
        except Exception:
            await self.storage.delete(object_key)
            raise

    async def list(self, *, session_id: UUID, tenant_id: str) -> Sequence[Evidence]:
        await self.session_service.get(session_id=session_id, tenant_id=tenant_id)
        return await self.repository.list_for_session(session_id, tenant_id)
