from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.averiq_api.config import get_settings
from apps.api.averiq_api.routers.audit import router as audit_router
from apps.api.averiq_api.routers.evidence import router as evidence_router
from apps.api.averiq_api.routers.management.credentials import (
    router as management_credentials_router,
)
from apps.api.averiq_api.routers.verification_sessions import request_id
from apps.api.averiq_api.routers.verification_sessions import (
    router as verification_sessions_router,
)
from apps.api.averiq_api.schemas.verification import (
    ErrorBody,
    ErrorEnvelope,
    ResponseMeta,
)
from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditPersistenceError, AuditService
from core.security.exceptions import AuthenticationError, AuthorizationError
from infrastructure.database import models  # noqa: F401
from infrastructure.database.base import Base
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.session import engine, session_factory

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Production/staging schema is owned by Alembic (`alembic upgrade head`,
    # run as an explicit deploy step) so the app never silently mutates a
    # real database's schema on startup. create_all() remains only as a
    # local development convenience for a throwaway database.
    if settings.app_env == "development":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="Averiq API",
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
    request: Request, _: AuthenticationError
) -> JSONResponse:
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
            await session.commit()
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


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "averiq-api", "version": settings.app_version}


@app.get("/ready", tags=["system"])
async def readiness() -> dict[str, str]:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exception:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exception
    return {"status": "ready"}
