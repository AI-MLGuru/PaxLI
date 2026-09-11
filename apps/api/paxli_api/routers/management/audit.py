from datetime import datetime

from fastapi import APIRouter, Depends, Request

from apps.api.paxli_api.dependencies import get_audit_service, get_principal
from apps.api.paxli_api.routers.verification_sessions import request_id
from apps.api.paxli_api.schemas.verification import (
    AuditEventListEnvelope,
    AuditEventResponse,
    ResponseMeta,
)
from core.audit.enums import AuditEventType
from core.audit.service import AuditService
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission

router = APIRouter(prefix="/management/audit-events", tags=["management-audit"])


@router.get("", response_model=AuditEventListEnvelope)
async def list_management_audit_events(
    request: Request,
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    event_type: AuditEventType | None = None,
    actor_id: str | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 100,
) -> AuditEventListEnvelope:
    """Governance-event retrieval (Invariant-12 remediation 3): the
    existing /verification-sessions/{id}/audit-events endpoint only ever
    covers session-scoped events. POLICY_ACTIVATED, CREDENTIAL_ISSUED/
    ROTATED/REVOKED, POLICY_ACTIVATION_FAILED, CREDENTIAL_OPERATION_FAILED,
    and any other non-session-scoped governed event had no API retrieval
    path at all before this -- durable, but not retrievable except by
    direct database access. Tenant is always the authenticated principal's
    own; there is no tenant_id parameter, so a client can never request
    another tenant's audit history (Invariant 12.34/12.35)."""
    require_permission(principal, Permission.AUDIT_READ)
    events = await audit_service.list_for_tenant(
        tenant_id=principal.tenant_id,
        event_type=event_type,
        actor_id=actor_id,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
        limit=limit,
    )
    return AuditEventListEnvelope(
        data=[AuditEventResponse.model_validate(event) for event in events],
        meta=ResponseMeta(request_id=request_id(request)),
    )
