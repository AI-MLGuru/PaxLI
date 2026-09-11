from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.decision.enums import DecisionOutcome
from core.policy.condition import Condition
from core.policy.enums import PolicyStatus
from core.policy.exceptions import PolicyActivationConflictError
from core.policy.gates import Gate
from core.policy.models import VerificationPolicy
from core.policy.requirements import EvidenceRequirement
from core.policy.rules import Rule
from core.policy.thresholds import ThresholdDefinition
from core.verification.enums import AssuranceLevel
from infrastructure.database.models.policy import PolicyRecord


class SqlAlchemyVerificationPolicyRepository:
    """Translates a partial-unique-index violation on
    ix_policies_one_active_per_tenant_assurance into
    PolicyActivationConflictError -- the concrete proof that the database,
    not application logic, is the final authority on activation races
    (Foundation-009 discovery question 8)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, policy: VerificationPolicy, idempotency_key: str | None = None
    ) -> VerificationPolicy:
        record = self._to_record(policy, idempotency_key)
        self.session.add(record)
        try:
            await self.session.flush()
        except IntegrityError as exception:
            raise PolicyActivationConflictError(
                f"a policy is already ACTIVE for tenant={policy.tenant_id!r} "
                f"assurance_level={policy.assurance_level.value!r}"
            ) from exception
        return self._to_domain(record)

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationPolicy | None:
        statement = select(PolicyRecord).where(
            PolicyRecord.tenant_id == tenant_id,
            PolicyRecord.idempotency_key == idempotency_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

    async def mark_superseded(
        self, policy_row_id: UUID, tenant_id: str, superseded_at: datetime
    ) -> None:
        record = await self.session.get(PolicyRecord, str(policy_row_id))
        if record is None or record.tenant_id != tenant_id:
            return
        record.status = PolicyStatus.SUPERSEDED.value
        record.superseded_at = superseded_at
        await self.session.flush()

    async def get(self, policy_row_id: UUID, tenant_id: str) -> VerificationPolicy | None:
        record = await self.session.get(PolicyRecord, str(policy_row_id))
        if record is None or record.tenant_id != tenant_id:
            return None
        return self._to_domain(record)

    async def get_active(
        self, tenant_id: str, assurance_level: AssuranceLevel
    ) -> VerificationPolicy | None:
        statement = select(PolicyRecord).where(
            PolicyRecord.tenant_id == tenant_id,
            PolicyRecord.assurance_level == assurance_level.value,
            PolicyRecord.status == PolicyStatus.ACTIVE.value,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

    async def get_version(
        self, policy_id: str, version: int, tenant_id: str
    ) -> VerificationPolicy | None:
        statement = select(PolicyRecord).where(
            PolicyRecord.tenant_id == tenant_id,
            PolicyRecord.policy_id == policy_id,
            PolicyRecord.version == version,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return self._to_domain(record) if record is not None else None

    async def get_max_version(self, policy_id: str, tenant_id: str) -> int:
        statement = select(PolicyRecord.version).where(
            PolicyRecord.tenant_id == tenant_id, PolicyRecord.policy_id == policy_id
        )
        versions = (await self.session.execute(statement)).scalars().all()
        return max(versions, default=0)

    async def list_versions(self, policy_id: str, tenant_id: str) -> Sequence[VerificationPolicy]:
        statement = (
            select(PolicyRecord)
            .where(PolicyRecord.tenant_id == tenant_id, PolicyRecord.policy_id == policy_id)
            .order_by(PolicyRecord.version)
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [self._to_domain(record) for record in records]

    def _to_record(
        self, policy: VerificationPolicy, idempotency_key: str | None = None
    ) -> PolicyRecord:
        return PolicyRecord(
            id=str(policy.id),
            policy_id=policy.policy_id,
            version=policy.version,
            tenant_id=policy.tenant_id,
            assurance_level=policy.assurance_level.value,
            schema_version=policy.schema_version,
            status=policy.status.value,
            evidence_requirements_json=[
                req.model_dump(mode="json") for req in policy.evidence_requirements
            ],
            conditions_json=(
                policy.conditions.model_dump() if policy.conditions is not None else None
            ),
            gates_json=[gate.model_dump(mode="json") for gate in policy.gates],
            rules_json=[rule.model_dump(mode="json") for rule in policy.rules],
            thresholds_json=[t.model_dump(mode="json") for t in policy.thresholds],
            default_outcome=(
                policy.default_outcome.value if policy.default_outcome is not None else None
            ),
            metadata_json=policy.metadata,
            canonical_hash=policy.canonical_hash,
            created_at=policy.created_at,
            activated_at=policy.activated_at,
            superseded_at=policy.superseded_at,
            supersedes_id=(str(policy.supersedes_id) if policy.supersedes_id else None),
            created_by=policy.created_by,
            idempotency_key=idempotency_key,
        )

    def _to_domain(self, record: PolicyRecord) -> VerificationPolicy:
        conditions: Condition | None = None
        if record.conditions_json is not None:
            conditions = TypeAdapter(Condition).validate_python(record.conditions_json)

        return VerificationPolicy(
            id=UUID(record.id),
            policy_id=record.policy_id,
            version=record.version,
            tenant_id=record.tenant_id,
            assurance_level=AssuranceLevel(record.assurance_level),
            schema_version=record.schema_version,
            status=PolicyStatus(record.status),
            evidence_requirements=tuple(
                EvidenceRequirement.model_validate(item)
                for item in record.evidence_requirements_json
            ),
            conditions=conditions,
            gates=tuple(Gate.model_validate(item) for item in record.gates_json),
            rules=tuple(Rule.model_validate(item) for item in record.rules_json),
            thresholds=tuple(
                ThresholdDefinition.model_validate(item) for item in record.thresholds_json
            ),
            default_outcome=(
                DecisionOutcome(record.default_outcome) if record.default_outcome else None
            ),
            metadata=record.metadata_json,
            canonical_hash=record.canonical_hash,
            created_at=record.created_at,
            activated_at=record.activated_at,
            superseded_at=record.superseded_at,
            supersedes_id=(UUID(record.supersedes_id) if record.supersedes_id else None),
            created_by=record.created_by,
        )
