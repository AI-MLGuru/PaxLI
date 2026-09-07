from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from apps.api.averiq_api.dependencies import get_audit_service, get_session_service
from apps.api.averiq_api.schemas.verification import (
    CreateVerificationSessionRequest,
    ErrorEnvelope,
    ResponseMeta,
    SessionEnvelope,
    VerificationSessionResponse,
)
from core.audit.enums import AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.verification.service import (
    SessionExpiredError,
    SessionNotFoundError,
    VerificationSessionService,
)

router = APIRouter(prefix="/verification-sessions", tags=["verification-sessions"])


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", f"req_{uuid4().hex}")


def tenant_header(x_tenant_id: str = Header(..., min_length=1, max_length=128)) -> str:
    return x_tenant_id


@router.post("", response_model=SessionEnvelope, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateVerificationSessionRequest,
    request: Request,
    service: VerificationSessionService = Depends(get_session_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    tenant_id: str = Depends(tenant_header),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SessionEnvelope:
    session = await service.create(
        tenant_id=tenant_id,
        external_reference=payload.external_reference,
        assurance_level=payload.assurance_level,
        idempotency_key=idempotency_key,
    )
    await audit_service.record(
        tenant_id=tenant_id,
        session_id=session.id,
        event_type=AuditEventType.SESSION_CREATED,
        component="verification_session_api",
        action="create_session",
        status=AuditStatus.SUCCESS,
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
    tenant_id: str = Depends(tenant_header),  # noqa: B008
) -> SessionEnvelope:
    try:
        session = await service.get(session_id=session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Verification session not found"
        ) from exc
    await audit_service.record(
        tenant_id=tenant_id,
        session_id=session.id,
        event_type=(
            AuditEventType.SESSION_EXPIRED
            if session.status.value == "EXPIRED"
            else AuditEventType.SESSION_RETRIEVED
        ),
        component="verification_session_api",
        action="retrieve_session",
        status=AuditStatus.SUCCESS,
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
    tenant_id: str = Depends(tenant_header),  # noqa: B008
) -> SessionEnvelope:
    try:
        session = await service.cancel(session_id=session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Verification session not found"
        ) from exc
    except SessionExpiredError as exc:
        raise HTTPException(
            status_code=409, detail="Verification session has expired"
        ) from exc
    await audit_service.record(
        tenant_id=tenant_id,
        session_id=session.id,
        event_type=AuditEventType.SESSION_CANCELLED,
        component="verification_session_api",
        action="cancel_session",
        status=AuditStatus.SUCCESS,
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        dedupe_key=f"session-cancelled:{session.id}",
    )
    return SessionEnvelope(
        data=VerificationSessionResponse.model_validate(session),
        meta=ResponseMeta(request_id=request_id(request)),
    )
