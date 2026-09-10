import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.evidence_result.classification import classify
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult, ModelReference
from core.security.classification import DataClassification
from core.security.keys import KeyProvider
from infrastructure.database.models.evidence_result import EvidenceResultRecord


class SqlAlchemyEvidenceResultRepository:
    """Encrypts HIGHLY_SENSITIVE result payloads before they reach storage,
    transparently to every caller: EvidenceResultService (and anything
    else) only ever sees a plain `EvidenceResult.result: dict | None`.
    Which evidence_types require protection is decided by
    core.evidence_result.classification.classify() -- never by caller input.
    """

    def __init__(self, session: AsyncSession, key_provider: KeyProvider, key_id: str) -> None:
        self.session = session
        self.key_provider = key_provider
        self.key_id = key_id

    async def add(self, evidence_result: EvidenceResult) -> EvidenceResult:
        record = await self._to_record(evidence_result)
        self.session.add(record)
        await self.session.flush()
        return await self._to_domain(record)

    async def get(self, evidence_result_id: UUID, tenant_id: str) -> EvidenceResult | None:
        record = await self.session.get(EvidenceResultRecord, str(evidence_result_id))
        if record is None or record.tenant_id != tenant_id:
            return None
        return await self._to_domain(record)

    async def list_for_session(
        self, session_id: UUID, tenant_id: str
    ) -> Sequence[EvidenceResult]:
        statement = (
            select(EvidenceResultRecord)
            .where(
                EvidenceResultRecord.session_id == str(session_id),
                EvidenceResultRecord.tenant_id == tenant_id,
            )
            .order_by(EvidenceResultRecord.produced_at)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [await self._to_domain(record) for record in records]

    async def list_for_session_by_type(
        self, session_id: UUID, tenant_id: str, evidence_type: EvidenceResultType
    ) -> Sequence[EvidenceResult]:
        statement = (
            select(EvidenceResultRecord)
            .where(
                EvidenceResultRecord.session_id == str(session_id),
                EvidenceResultRecord.tenant_id == tenant_id,
                EvidenceResultRecord.evidence_type == evidence_type.value,
            )
            .order_by(EvidenceResultRecord.produced_at)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [await self._to_domain(record) for record in records]

    async def _to_record(self, evidence_result: EvidenceResult) -> EvidenceResultRecord:
        result_json = None
        result_ciphertext = None
        result_key_id = None
        if evidence_result.result is not None:
            if classify(evidence_result.evidence_type) == DataClassification.HIGHLY_SENSITIVE:
                plaintext = json.dumps(evidence_result.result).encode("utf-8")
                result_ciphertext = await self.key_provider.encrypt(plaintext, self.key_id)
                result_key_id = self.key_id
            else:
                result_json = evidence_result.result

        return EvidenceResultRecord(
            id=str(evidence_result.id),
            tenant_id=evidence_result.tenant_id,
            session_id=str(evidence_result.session_id),
            evidence_type=evidence_result.evidence_type.value,
            schema_version=evidence_result.schema_version,
            status=evidence_result.status.value,
            result_json=result_json,
            result_ciphertext=result_ciphertext,
            result_key_id=result_key_id,
            reason_codes_json=list(evidence_result.reason_codes),
            score=evidence_result.score,
            quality=evidence_result.quality,
            producer=evidence_result.producer,
            producer_version=evidence_result.producer_version,
            model_reference_json=(
                evidence_result.model_reference.model_dump()
                if evidence_result.model_reference
                else None
            ),
            source_reference=(
                str(evidence_result.source_reference)
                if evidence_result.source_reference
                else None
            ),
            parent_evidence_result_ids_json=[
                str(i) for i in evidence_result.parent_evidence_result_ids
            ],
            supersedes_id=(
                str(evidence_result.supersedes_id) if evidence_result.supersedes_id else None
            ),
            produced_at=evidence_result.produced_at,
            persisted_at=evidence_result.persisted_at,
            integrity_reference=evidence_result.integrity_reference,
            retention_until=evidence_result.retention_until,
        )

    async def _to_domain(self, record: EvidenceResultRecord) -> EvidenceResult:
        result: dict[str, Any] | None
        if record.result_ciphertext is not None:
            assert record.result_key_id is not None
            plaintext = await self.key_provider.decrypt(
                record.result_ciphertext, record.result_key_id
            )
            result = json.loads(plaintext.decode("utf-8"))
        else:
            result = record.result_json

        return EvidenceResult(
            id=UUID(record.id),
            tenant_id=record.tenant_id,
            session_id=UUID(record.session_id),
            evidence_type=EvidenceResultType(record.evidence_type),
            schema_version=record.schema_version,
            status=EvidenceResultStatus(record.status),
            result=result,
            reason_codes=tuple(record.reason_codes_json),
            score=record.score,
            quality=record.quality,
            producer=record.producer,
            producer_version=record.producer_version,
            model_reference=(
                ModelReference.model_validate(record.model_reference_json)
                if record.model_reference_json
                else None
            ),
            source_reference=UUID(record.source_reference) if record.source_reference else None,
            parent_evidence_result_ids=tuple(
                UUID(i) for i in record.parent_evidence_result_ids_json
            ),
            supersedes_id=UUID(record.supersedes_id) if record.supersedes_id else None,
            produced_at=record.produced_at,
            persisted_at=record.persisted_at,
            integrity_reference=record.integrity_reference,
            retention_until=record.retention_until,
        )
