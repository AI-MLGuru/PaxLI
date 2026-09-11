from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.averiq_api.config import Settings, get_settings
from core.audit.service import AuditService
from core.evidence.service import EvidenceService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.service import PolicyService
from core.rate_limit.enums import RateLimitScope
from core.rate_limit.evaluation import FailMode, evaluate_admission
from core.rate_limit.keys import build_scope_key
from core.rate_limit.limiter import RateLimiterProtocol
from core.rate_limit.metrics import RateLimitMetrics
from core.security.authentication import AuthenticatedPrincipal, authenticate_bearer
from core.security.credentials import CredentialService
from core.verification.service import VerificationSessionService
from infrastructure.database.repositories.audit_event import (
    SqlAlchemyAuditEventRepository,
)
from infrastructure.database.repositories.credential import SqlAlchemyCredentialStore
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import get_db_session, session_factory
from infrastructure.deletion.reconciliation import (
    SqlAlchemyEvidenceDeletionReconciler,
    SqlAlchemyEvidenceResultDeletionReconciler,
)
from infrastructure.rate_limit.network_source import (
    get_network_source_hmac_key,
    hash_network_source,
)
from infrastructure.rate_limit.postgres_limiter import PostgresRateLimiter
from infrastructure.rate_limit.rules import authenticated_rules, pre_auth_rule
from infrastructure.security.hashing import ScryptSecretHasher
from infrastructure.security.local_key_provider import get_local_key_provider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

# Module-level, not request-scoped: PostgresRateLimiter is stateless besides
# holding the session factory, and RateLimitMetrics is meant to accumulate
# across requests (same pattern as core.reliability.metrics.ReliabilityMetrics
# instances in main.py).
_RATE_LIMITER = PostgresRateLimiter(session_factory)
RATE_LIMIT_METRICS = RateLimitMetrics()


async def get_session_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[VerificationSessionService]:
    policy_service = PolicyService(
        SqlAlchemyVerificationPolicyRepository(db_session),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        EvidenceResultSchemaCatalog(),
    )
    yield VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(db_session),
        policy_service,
        session_ttl_minutes=settings.session_ttl_minutes,
    )


async def get_evidence_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[EvidenceService]:
    session_repository = SqlAlchemyVerificationSessionRepository(db_session)
    key_provider = get_local_key_provider(
        key_id=settings.evidence_encryption_key_id,
        encoded_key=settings.evidence_encryption_key,
    )
    storage = EncryptedObjectStorage(
        MinioObjectStorage(settings), key_provider, settings.evidence_encryption_key_id
    )
    yield EvidenceService(
        SqlAlchemyEvidenceRepository(db_session),
        VerificationSessionService(
            session_repository,
            session_ttl_minutes=settings.session_ttl_minutes,
        ),
        storage,
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        deletion_reconciler=SqlAlchemyEvidenceDeletionReconciler(session_factory, storage),
    )


async def get_evidence_result_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[EvidenceResultService]:
    key_provider = get_local_key_provider(
        key_id=settings.evidence_encryption_key_id,
        encoded_key=settings.evidence_encryption_key,
    )
    yield EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(
            db_session, key_provider, settings.evidence_encryption_key_id
        ),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        deletion_reconciler=SqlAlchemyEvidenceResultDeletionReconciler(
            session_factory, key_provider, settings.evidence_encryption_key_id
        ),
    )


async def get_audit_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncIterator[AuditService]:
    yield AuditService(SqlAlchemyAuditEventRepository(db_session))


async def get_credential_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncIterator[CredentialService]:
    yield CredentialService(SqlAlchemyCredentialStore(db_session), ScryptSecretHasher())


def get_rate_limiter() -> RateLimiterProtocol:
    return _RATE_LIMITER


async def enforce_pre_auth_admission(
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
) -> None:
    """Runs BEFORE authenticate_bearer()'s credential lookup -- wired as a
    sub-dependency of get_principal below, which is the only way to
    guarantee this executes before authenticate_bearer is ever called
    (FastAPI resolves every Depends() of a function before invoking that
    function's own body). SEC-7.32's credential-attack surface must never
    reach the expensive scrypt/credential-lookup path once throttled
    (Foundation-010 discovery). Fail-closed: this is the security-critical
    endpoint class."""
    client_host = request.client.host if request.client is not None else "unknown"
    hmac_key = get_network_source_hmac_key(
        key_id=settings.rate_limit_network_source_hmac_key_id,
        encoded_key=settings.rate_limit_network_source_hmac_key,
    )
    network_source_key = hash_network_source(
        client_host,
        key_id=settings.rate_limit_network_source_hmac_key_id,
        key=hmac_key,
    )
    scope_key = build_scope_key(
        RateLimitScope.NETWORK_SOURCE, "authenticate", network_source_key=network_source_key
    )
    rule = pre_auth_rule(
        limit=settings.rate_limit_auth_attempts_per_window,
        window_seconds=settings.rate_limit_auth_window_seconds,
    )
    await evaluate_admission(
        rules_and_keys=[(rule, scope_key)],
        limiter=limiter,
        fail_mode="closed",
        metrics=RATE_LIMIT_METRICS,
    )


async def get_principal(
    authorization: str | None = Header(default=None),
    credential_service: CredentialService = Depends(get_credential_service),  # noqa: B008
    _pre_auth_admission: None = Depends(enforce_pre_auth_admission),  # noqa: B008
) -> AuthenticatedPrincipal:
    return await authenticate_bearer(authorization, credential_service)


async def enforce_rate_limit(
    principal: AuthenticatedPrincipal,
    *,
    operation: str,
    limit: int,
    window_seconds: int,
    fail_mode: FailMode,
    limiter: RateLimiterProtocol,
) -> None:
    """Authenticated, tenant+credential-scoped admission check -- called
    explicitly inside a route body immediately after require_permission(),
    the same style already used there (a plain call, not a second Depends
    layer). Most-restrictive-wins across the tenant and credential scopes
    (Foundation-010 discovery decision #3)."""
    rules = authenticated_rules(limit=limit, window_seconds=window_seconds)
    rules_and_keys = [
        (
            rule,
            build_scope_key(
                rule.scope,
                operation,
                tenant_id=principal.tenant_id,
                credential_id=str(principal.credential_id),
            ),
        )
        for rule in rules
    ]
    await evaluate_admission(
        rules_and_keys=rules_and_keys,
        limiter=limiter,
        fail_mode=fail_mode,
        metrics=RATE_LIMIT_METRICS,
    )
