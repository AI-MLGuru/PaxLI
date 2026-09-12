import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.paxli_api.config import get_settings
from apps.api.paxli_api.routers.audit import router as audit_router
from apps.api.paxli_api.routers.evidence import router as evidence_router
from apps.api.paxli_api.routers.management.audit import (
    router as management_audit_router,
)
from apps.api.paxli_api.routers.management.credentials import (
    router as management_credentials_router,
)
from apps.api.paxli_api.routers.management.evidence_results import (
    router as management_evidence_results_router,
)
from apps.api.paxli_api.routers.verification_sessions import request_id
from apps.api.paxli_api.routers.verification_sessions import (
    router as verification_sessions_router,
)
from apps.api.paxli_api.schemas.verification import (
    ErrorBody,
    ErrorEnvelope,
    ResponseMeta,
)
from apps.api.paxli_api.transport_security import validate_production_transport_security
from core.audit.enums import (
    UNATTRIBUTED_TENANT_ID,
    AuditActorType,
    AuditDurability,
    AuditEventType,
    AuditStatus,
)
from core.audit.service import AuditPersistenceError, AuditService
from core.deletion.exceptions import DeletionAlreadyRequestedError, DeletionBlockedByDependentsError
from core.evidence.service import EvidenceDeletedError
from core.policy.exceptions import NoActivePolicyError
from core.rate_limit.exceptions import RateLimitExceededError
from core.reliability.health import check_dependency
from core.security.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CredentialStateError,
    IdempotentReplayWithoutSecretError,
)
from infrastructure.database import models  # noqa: F401
from infrastructure.database.base import Base
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.session import engine, session_factory
from infrastructure.observability.logging import configure_logging
from infrastructure.observability.reliability_logging import log_reliability_metrics
from infrastructure.reliability.dependency_health import (
    READY_STATES,
    classify,
)
from infrastructure.reliability.minio_policies import BREAKER as MINIO_BREAKER
from infrastructure.reliability.minio_policies import METRICS as MINIO_METRICS
from infrastructure.reliability.minio_policies import MinioOperationError
from infrastructure.reliability.postgres_policies import BREAKER as POSTGRES_BREAKER
from infrastructure.reliability.postgres_policies import METRICS as POSTGRES_METRICS
from infrastructure.reliability.postgres_policies import PostgresOperationError, guarded_commit

settings = get_settings()
validate_production_transport_security(settings)
configure_logging(settings)

logger = logging.getLogger(__name__)

_health_minio_client: object | None = None


def _get_health_minio_client() -> object:
    global _health_minio_client
    if _health_minio_client is None:
        from minio import Minio

        _health_minio_client = Minio(
            settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
            secure=settings.storage_secure,
        )
    return _health_minio_client


async def _check_postgres() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_minio() -> None:
    client = _get_health_minio_client()
    await asyncio.to_thread(client.bucket_exists, settings.storage_bucket)  # type: ignore[attr-defined]


async def _report_reliability_metrics_periodically() -> None:
    while True:
        await asyncio.sleep(60)
        log_reliability_metrics(
            dependency="postgres",
            snapshot=POSTGRES_METRICS.snapshot(),
            circuit_state=POSTGRES_BREAKER.state.value,
        )
        log_reliability_metrics(
            dependency="minio",
            snapshot=MINIO_METRICS.snapshot(),
            circuit_state=MINIO_BREAKER.state.value,
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Production/staging schema is owned by Alembic (`alembic upgrade head`,
    # run as an explicit deploy step) so the app never silently mutates a
    # real database's schema on startup. create_all() remains only as a
    # local development convenience for a throwaway database.
    if settings.app_env == "development":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    metrics_task = asyncio.create_task(_report_reliability_metrics_periodically())
    try:
        yield
    finally:
        metrics_task.cancel()


app = FastAPI(
    title="PaxLI API",
    description="Identity verification and biometric trust infrastructure by PaxAlpha.",
    version=settings.app_version,
    lifespan=lifespan,
)
app.state.settings = settings
# Overridable so tests can point authorization-denial auditing at their own
# isolated database, the same way `app.dependency_overrides` redirects
# request-scoped dependencies.
app.state.db_session_factory = session_factory
app.include_router(verification_sessions_router, prefix=settings.api_prefix)
app.include_router(evidence_router, prefix=settings.api_prefix)
app.include_router(audit_router, prefix=settings.api_prefix)
app.include_router(management_credentials_router, prefix=settings.api_prefix)
app.include_router(management_audit_router, prefix=settings.api_prefix)
app.include_router(management_evidence_results_router, prefix=settings.api_prefix)


def error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(code=code, message=message),
        meta=ResponseMeta(request_id=request.headers.get("X-Request-ID", "req_unknown")),
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exception: HTTPException) -> JSONResponse:
    code = "VERIFICATION_SESSION_NOT_FOUND" if exception.status_code == 404 else "REQUEST_ERROR"
    return error_response(request, code, str(exception.detail), exception.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, _: RequestValidationError) -> JSONResponse:
    return error_response(request, "INVALID_REQUEST", "The request payload is invalid.", 422)


@app.exception_handler(AuditPersistenceError)
async def audit_persistence_exception_handler(
    request: Request, _: AuditPersistenceError
) -> JSONResponse:
    return error_response(
        request,
        "AUDIT_PERSISTENCE_FAILED",
        "The security audit record could not be persisted.",
        503,
    )


@app.exception_handler(AuthenticationError)
async def authentication_exception_handler(
    request: Request, exception: AuthenticationError
) -> JSONResponse:
    # A failed authentication attempt is security-relevant (SEC-7.29.1) and
    # gets its own required, durable audit event, for the same reason and in
    # the same shape as authorization denial: no governed effect exists to
    # gate here, so this is its own independent unit of work.
    try:
        async with request.app.state.db_session_factory() as session:
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            await audit_service.record(
                tenant_id=exception.tenant_id or UNATTRIBUTED_TENANT_ID,
                event_type=AuditEventType.AUTHENTICATION_FAILED,
                component="authentication",
                action="authenticate_bearer",
                status=AuditStatus.FAILURE,
                actor_type=AuditActorType.CLIENT,
                actor_id=exception.credential_id,
                request_id=request_id(request),
                correlation_id=request.headers.get("X-Correlation-ID"),
                durability=AuditDurability.REQUIRED,
            )
            await guarded_commit(session)
    except Exception:
        return error_response(
            request,
            "AUDIT_PERSISTENCE_FAILED",
            "The security audit record could not be persisted.",
            503,
        )
    return error_response(request, "AUTHENTICATION_FAILED", "Invalid credentials", 401)


@app.exception_handler(AuthorizationError)
async def authorization_exception_handler(
    request: Request, exception: AuthorizationError
) -> JSONResponse:
    # Authorization denial is a security-relevant action (SEC-7.29.1,
    # Invariant 12.9.46) and gets its own required, durable audit event.
    # There is no governed effect to gate here (the request was already
    # denied), so this is its own independent unit of work rather than
    # sharing the request's (rolled-back) session.
    try:
        async with request.app.state.db_session_factory() as session:
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            await audit_service.record(
                tenant_id=exception.tenant_id,
                session_id=UUID(exception.session_id) if exception.session_id else None,
                event_type=AuditEventType.AUTHORIZATION_DENIED,
                component="authorization",
                action="require_permission",
                status=AuditStatus.FAILURE,
                actor_type=AuditActorType.CLIENT,
                actor_id=exception.actor_id,
                request_id=request_id(request),
                correlation_id=request.headers.get("X-Correlation-ID"),
                metadata={"required_permission": exception.required_permission},
                durability=AuditDurability.REQUIRED,
            )
            await guarded_commit(session)
    except Exception:
        # Any failure recording the required denial audit (a wrapped
        # AuditPersistenceError, or the underlying database being
        # unreachable) must not be silently discarded (Invariant 12.15) or
        # reported as an ordinary, fully-audited 403 (12.9/12.65).
        return error_response(
            request,
            "AUDIT_PERSISTENCE_FAILED",
            "The security audit record could not be persisted.",
            503,
        )
    return error_response(request, "AUTHORIZATION_DENIED", "Operation not permitted", 403)


@app.exception_handler(CredentialStateError)
async def credential_state_exception_handler(
    request: Request, exception: CredentialStateError
) -> JSONResponse:
    # Invariant-12 remediation 2: a material, externally initiated
    # credential-management failure (rotating/revoking an already-inactive
    # credential) is a governance-relevant action MUST-auditable under
    # 12.43, following the exact same independent-transaction pattern as
    # AUTHENTICATION_FAILED/AUTHORIZATION_DENIED above -- there is no
    # governed effect to gate, so this is its own unit of work.
    try:
        async with request.app.state.db_session_factory() as session:
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            await audit_service.record(
                tenant_id=exception.tenant_id or UNATTRIBUTED_TENANT_ID,
                event_type=AuditEventType.CREDENTIAL_OPERATION_FAILED,
                component="credential_management_api",
                action="credential_state_transition",
                status=AuditStatus.FAILURE,
                actor_type=AuditActorType.CLIENT,
                actor_id=exception.actor_id,
                request_id=request_id(request),
                correlation_id=request.headers.get("X-Correlation-ID"),
                metadata={"target_credential_id": exception.target_credential_id},
                durability=AuditDurability.REQUIRED,
            )
            await guarded_commit(session)
    except Exception:
        return error_response(
            request,
            "AUDIT_PERSISTENCE_FAILED",
            "The security audit record could not be persisted.",
            503,
        )
    return error_response(request, "CREDENTIAL_STATE_CONFLICT", str(exception), 409)


@app.exception_handler(IdempotentReplayWithoutSecretError)
async def idempotent_replay_without_secret_exception_handler(
    request: Request, exception: IdempotentReplayWithoutSecretError
) -> JSONResponse:
    # Invariant-12 remediation, explicit decision: a retried credential
    # issue/rotate cannot silently return "success" without the secret --
    # the stored record only ever holds a one-way hash (SEC-7.9.9), so the
    # original secret is unrecoverable. A clear error beats a response the
    # caller could mistake for having received a secret it didn't get.
    return error_response(request, "IDEMPOTENT_REPLAY_SECRET_UNAVAILABLE", str(exception), 409)


@app.exception_handler(EvidenceDeletedError)
async def evidence_deleted_exception_handler(
    request: Request, _: EvidenceDeletedError
) -> JSONResponse:
    # Invariant-06 remediation Phase 4, firm choice: a deleted evidence ID
    # must remain distinguishable from one that never existed (410, not
    # 404) -- but the response body must leak NO deletion metadata (no
    # basis/actor/timestamps/object key/checksum). Deliberately NOT built
    # through error_response()/ErrorEnvelope: the approved shape here is
    # flat, not the app's usual {error: {...}, meta: {...}} nesting.
    return JSONResponse(
        status_code=410,
        content={
            "code": "EVIDENCE_DELETED",
            "message": "This evidence has been deleted.",
            "category": "NOT_FOUND",
            "request_id": request_id(request),
        },
    )


@app.exception_handler(DeletionAlreadyRequestedError)
async def deletion_already_requested_exception_handler(
    request: Request, exception: DeletionAlreadyRequestedError
) -> JSONResponse:
    # A concurrent deletion request lost the race for the same resource
    # (core.deletion.exceptions.DeletionAlreadyRequestedError -- a
    # translation of the tombstone table's primary key, same shape as
    # PolicyActivationConflictError). The deletion the caller wanted still
    # proceeds via the winning request; this is a retryable conflict, not a
    # material governed-action failure, so no independent failure audit is
    # recorded here.
    return error_response(request, "DELETION_ALREADY_REQUESTED", str(exception), 409)


@app.exception_handler(NoActivePolicyError)
async def no_active_policy_exception_handler(
    request: Request, exception: NoActivePolicyError
) -> JSONResponse:
    # DE-002/DE-003 §1 early policy binding: session creation now depends
    # on policy governance, and this is its explicit failure path -- a
    # plain creation-time conflict (no policy has been activated for this
    # tenant/assurance_level yet), never a Decision Engine INCONCLUSIVE,
    # since no session exists yet to attach one to. POLICY_NOT_FOUND is the
    # exact code DE-003 §8 reserves for this case.
    return error_response(request, "POLICY_NOT_FOUND", str(exception), 409)


@app.exception_handler(DeletionBlockedByDependentsError)
async def deletion_blocked_by_dependents_exception_handler(
    request: Request, exception: DeletionBlockedByDependentsError
) -> JSONResponse:
    # Invariant-06 remediation Phase 6 finding: a foreign key with no ON
    # DELETE behavior (EvidenceResult.source_reference/supersedes_id) means
    # a physical DELETE against a resource with a dependent would fail with
    # a ForeignKeyViolation that no retry could ever resolve. Rejected at
    # request_deletion() time instead, before any tombstone or storage
    # delete happens -- a clean, actionable 409 rather than a permanently
    # stuck reconciliation.
    return error_response(request, "DELETION_BLOCKED_BY_DEPENDENTS", str(exception), 409)


@app.exception_handler(RateLimitExceededError)
async def rate_limit_exceeded_exception_handler(
    request: Request, exception: RateLimitExceededError
) -> JSONResponse:
    # API-6.23.1-6.23.4: 429, stable RATE_LIMITED code, Retry-After header,
    # no limiter internals in the message (which scope tripped stays out of
    # the response body -- it's only in the exception object for logging).
    # Built directly rather than through error_response(): that helper has
    # no header parameter, and this is the only call site that needs one.
    body = ErrorEnvelope(
        error=ErrorBody(code="RATE_LIMITED", message="Rate limit exceeded"),
        meta=ResponseMeta(request_id=request.headers.get("X-Request-ID", "req_unknown")),
    )
    return JSONResponse(
        status_code=429,
        content=body.model_dump(mode="json"),
        headers={"Retry-After": str(exception.retry_after_seconds)},
    )


@app.exception_handler(PostgresOperationError)
async def postgres_operation_exception_handler(
    request: Request, _: PostgresOperationError
) -> JSONResponse:
    return error_response(
        request, "POSTGRES_OPERATION_FAILED", "The database operation could not be completed.", 503
    )


@app.exception_handler(MinioOperationError)
async def minio_operation_exception_handler(
    request: Request, _: MinioOperationError
) -> JSONResponse:
    return error_response(
        request, "STORAGE_OPERATION_FAILED", "The storage operation could not be completed.", 503
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exception: Exception) -> JSONResponse:
    # WF-006 Finding E / WF-HV-006: closes the gap where a genuine,
    # unclassified infrastructure failure (e.g. a raw DB exception from
    # one of DecisionOrchestrator.evaluate_and_persist()'s read steps,
    # which sit outside PostgresOperationError's guarded-commit-only
    # wrapping) previously propagated past every specific handler above
    # and fell through to Starlette's bare, non-JSON "Internal Server
    # Error" text -- a real client-visible violation of this app's own
    # {error: {...}, meta: {...}} contract every other response follows,
    # confirmed live by injecting exactly this failure through the real
    # /submit path. Logged server-side with full detail for observability
    # (SEC-7.29's "underlying failure MUST remain observable... without
    # exposing sensitive internals to clients"); the client only ever
    # sees a generic message, never the exception's own text.
    logger.error(
        "unhandled_exception",
        extra={"path": request.url.path, "method": request.method},
        exc_info=True,
    )
    return error_response(
        request, "INTERNAL_ERROR", "An unexpected error occurred.", 500
    )


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "paxli-api", "version": settings.app_version}


@app.get("/ready", tags=["system"])
async def readiness() -> JSONResponse:
    postgres_health = await check_dependency("postgres", _check_postgres, timeout_seconds=2.0)
    storage_health = await check_dependency("storage", _check_minio, timeout_seconds=2.0)

    dependencies = {
        "postgres": classify(postgres_health).value,
        "storage": classify(storage_health).value,
    }
    ready_values = {state.value for state in READY_STATES}
    is_ready = all(classify(h).value in ready_values for h in (postgres_health, storage_health))
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "not_ready",
            "dependencies": dependencies,
        },
    )
