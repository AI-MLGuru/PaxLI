from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.averiq_api.dependencies import get_audit_service, get_session_service
from apps.api.averiq_api.routers.verification_sessions import request_id, tenant_header
from apps.api.averiq_api.schemas.verification import (
    AuditEventListEnvelope,
    AuditEventResponse,
    ResponseMeta,
)
from core.audit.service import AuditService
from core.verification.service import SessionNotFoundError, VerificationSessionService

router = APIRouter(prefix="/verification-sessions", tags=["audit"])


@router.get("/{session_id}/audit-events", response_model=AuditEventListEnvelope)
async def list_audit_events(
    session_id: UUID,
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    session_service: VerificationSessionService = Depends(get_session_service),
    tenant_id: str = Depends(tenant_header),  # noqa: B008
) -> AuditEventListEnvelope:
    try:
        await session_service.get(session_id=session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    events = await audit_service.list_for_session(session_id=session_id, tenant_id=tenant_id)
    return AuditEventListEnvelope(
        data=[AuditEventResponse.model_validate(event) for event in events],
        meta=ResponseMeta(request_id=request_id(request)),
    )
