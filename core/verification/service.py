from uuid import UUID

from core.policy.exceptions import NoActivePolicyError
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.models import VerificationSession
from core.verification.repository import VerificationSessionRepository


class SessionNotFoundError(Exception):
    pass


class SessionExpiredError(Exception):
    pass


class VerificationSessionService:
    def __init__(
        self,
        repository: VerificationSessionRepository,
        policy_service: PolicyService | None = None,
        session_ttl_minutes: int = 30,
    ) -> None:
        self.repository = repository
        # Optional (DE-002/DE-003 §1): the majority of this service's
        # call sites (EvidenceService's internal use, most tests) only ever
        # call get()/cancel(), never create(), and have no need to resolve
        # a policy at all -- same shape as EvidenceResultService's optional
        # deletion_reconciler. create() raises a clear RuntimeError if this
        # is unset, rather than silently skipping policy binding.
        self.policy_service = policy_service
        self.session_ttl_minutes = session_ttl_minutes

    async def create(
        self,
        *,
        tenant_id: str,
        external_reference: str | None,
        assurance_level: AssuranceLevel,
        idempotency_key: str | None = None,
    ) -> VerificationSession:
        """Raises NoActivePolicyError (core.policy.exceptions) if no ACTIVE
        policy exists for (tenant_id, assurance_level) -- DE-002 §1's early
        policy binding makes session creation depend on policy governance.
        A plain creation-time failure: no session row is created, no
        Decision Engine INCONCLUSIVE, since there is no session yet to
        attach one to.

        `idempotency_key`, if supplied and already resolved, returns the
        original session -- its original pin, unchanged, never re-resolved
        against whatever policy happens to be active now (idempotency is
        already free here: the persisted row already carries the pin from
        the first, real attempt)."""
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(tenant_id, idempotency_key)
            if existing is not None:
                return existing

        if self.policy_service is None:
            raise RuntimeError(
                "VerificationSessionService was constructed without a policy_service"
            )
        policy = await self.policy_service.get_active(
            tenant_id=tenant_id, assurance_level=assurance_level
        )
        if policy is None:
            raise NoActivePolicyError(
                f"no ACTIVE policy for tenant={tenant_id!r} "
                f"assurance_level={assurance_level.value!r}"
            )

        session = VerificationSession.create(
            tenant_id=tenant_id,
            external_reference=external_reference,
            assurance_level=assurance_level,
            ttl_minutes=self.session_ttl_minutes,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_hash=policy.canonical_hash,
        )
        return await self.repository.add(session, idempotency_key)

    async def get(self, *, session_id: UUID, tenant_id: str) -> VerificationSession:
        session = await self.repository.get(session_id, tenant_id)
        if session is None:
            raise SessionNotFoundError
        if session.expire_if_needed():
            await self.repository.update(session)
        return session

    async def cancel(self, *, session_id: UUID, tenant_id: str) -> VerificationSession:
        session = await self.get(session_id=session_id, tenant_id=tenant_id)
        if session.status == VerificationStatus.EXPIRED:
            raise SessionExpiredError
        session.transition_to(VerificationStatus.CANCELLED)
        return await self.repository.update(session)
