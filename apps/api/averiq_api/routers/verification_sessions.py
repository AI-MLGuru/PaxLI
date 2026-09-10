from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from apps.api.averiq_api.config import Settings, get_settings
from apps.api.averiq_api.dependencies import (
    enforce_rate_limit,
    get_audit_service,
    get_principal,
    get_rate_limiter,
    get_session_service,
)
from apps.api.averiq_api.schemas.verification import (
    CreateVerificationSessionRequest,
    ErrorEnvelope,
    ResponseMeta,
    SessionEnvelope,
    VerificationSessionResponse,
)
from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.rate_limit.limiter import RateLimiterProtocol
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission
from core.verification.service import (
    SessionExpiredError,
    SessionNotFoundError,
    VerificationSessionService,
)

router = APIRouter(prefix="/verification-sessions", tags=["verification-sessions"])


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", f"req_{uuid4().hex}")


def tenant_from_principal(principal: AuthenticatedPrincipal = Depends(get_principal)) -> str:
    return principal.tenant_id


@router.post("", response_model=SessionEnvelope, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateVerificationSessionRequest,
    request: Request,
    service: VerificationSessionService = Depends(get_session_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SessionEnvelope:
    require_permission(principal, Permission.VERIFICATION_CREATE)
    # Operational endpoint class -> fail_mode="open": a limiter outage must
    # not itself take down verification-session creation (SEC-7.32.2,
    # Foundation-010 review guardrail #2 -- this bypasses the limiter only,
    # never authentication/authorization, which already ran above).
    await enforce_rate_limit(
        principal,
        operation="verification_create",
        limit=settings.rate_limit_verification_create_per_window,
        window_seconds=settings.rate_limit_verification_create_window_seconds,
        fail_mode="open",
        limiter=limiter,
    )
    session = await service.create(
        tenant_id=principal.tenant_id,
        external_reference=payload.external_reference,
        assurance_level=payload.assurance_level,
        idempotency_key=idempotency_key,
    )
    await audit_service.record(
        tenant_id=principal.tenant_id,
        session_id=session.id,
        event_type=AuditEventType.SESSION_CREATED,
        component="verification_session_api",
        action="create_session",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"assurance_level": session.assurance_level.value},
        dedupe_key=f"session-created:{session.id}",
    )
    return SessionEnvelope(
        data=VerificationSessionResponse.model_validate(session),
        meta=ResponseMeta(request_id=request_id(request)),
    )


@router.get(
    "/{session_id}",
    response_model=SessionEnvelope,
    responses={404: {"model": ErrorEnvelope}},
)
async def get_session(
    session_id: UUID,
    request: Request,
    service: VerificationSessionService = Depends(get_session_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
) -> SessionEnvelope:
    require_permission(principal, Permission.VERIFICATION_READ, session_id=str(session_id))
    try:
        session = await service.get(session_id=session_id, tenant_id=principal.tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    await audit_service.record(
        tenant_id=principal.tenant_id,
        session_id=session.id,
        event_type=(
            AuditEventType.SESSION_EXPIRED
            if session.status.value == "EXPIRED"
            else AuditEventType.SESSION_RETRIEVED
        ),
        component="verification_session_api",
        action="retrieve_session",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    return SessionEnvelope(
        data=VerificationSessionResponse.model_validate(session),
        meta=ResponseMeta(request_id=request_id(request)),
    )


@router.post(
    "/{session_id}/cancel",
    response_model=SessionEnvelope,
    responses={404: {"model": ErrorEnvelope}},
)
async def cancel_session(
    session_id: UUID,
    request: Request,
    service: VerificationSessionService = Depends(get_session_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
) -> SessionEnvelope:
    require_permission(principal, Permission.VERIFICATION_CANCEL, session_id=str(session_id))
    try:
        session = await service.cancel(session_id=session_id, tenant_id=principal.tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=409, detail="Verification session has expired") from exc
    await audit_service.record(
        tenant_id=principal.tenant_id,
        session_id=session.id,
        event_type=AuditEventType.SESSION_CANCELLED,
        component="verification_session_api",
        action="cancel_session",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        dedupe_key=f"session-cancelled:{session.id}",
    )
    return SessionEnvelope(
        data=VerificationSessionResponse.model_validate(session),
        meta=ResponseMeta(request_id=request_id(request)),
    )
