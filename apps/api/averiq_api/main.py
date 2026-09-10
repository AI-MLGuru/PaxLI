from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from apps.api.averiq_api.routers.verification_sessions import (
    router as verification_sessions_router,
)
from apps.api.averiq_api.schemas.verification import (
    ErrorBody,
    ErrorEnvelope,
    ResponseMeta,
)
from core.audit.service import AuditPersistenceError
from core.security.exceptions import AuthenticationError, AuthorizationError
from infrastructure.database import models  # noqa: F401
from infrastructure.database.base import Base
from infrastructure.database.session import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
async def authorization_exception_handler(request: Request, _: AuthorizationError) -> JSONResponse:
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
