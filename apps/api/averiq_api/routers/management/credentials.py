from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from apps.api.averiq_api.dependencies import (
    get_audit_service,
    get_credential_service,
    get_principal,
)
from apps.api.averiq_api.routers.verification_sessions import request_id
from apps.api.averiq_api.schemas.security import (
    IssueCredentialRequest,
    IssuedCredentialEnvelope,
    IssuedCredentialResponse,
    RotateCredentialRequest,
)
from apps.api.averiq_api.schemas.verification import ResponseMeta
from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission
from core.security.credentials import CredentialService
from core.security.exceptions import AuthenticationError, CredentialStateError

router = APIRouter(prefix="/management/credentials", tags=["management-credentials"])


@router.post("", response_model=IssuedCredentialEnvelope, status_code=status.HTTP_201_CREATED)
async def issue_credential(
    payload: IssueCredentialRequest,
    request: Request,
    service: CredentialService = Depends(get_credential_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
) -> IssuedCredentialEnvelope:
    require_permission(principal.permissions, Permission.CREDENTIAL_MANAGE)
    expires_in = timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    issued = await service.issue(
        tenant_id=principal.tenant_id,
        name=payload.name,
        scope=payload.scope,
        expires_in=expires_in,
    )
    await audit_service.record(
        tenant_id=principal.tenant_id,
        event_type=AuditEventType.CREDENTIAL_ISSUED,
        component="credential_management_api",
        action="issue_credential",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"issued_credential_id": str(issued.credential_id), "scope": issued.scope.value},
    )
    return IssuedCredentialEnvelope(
        data=IssuedCredentialResponse.model_validate(issued),
        meta=ResponseMeta(request_id=request_id(request)),
    )


@router.post("/{credential_id}/rotate", response_model=IssuedCredentialEnvelope)
async def rotate_credential(
    credential_id: UUID,
    payload: RotateCredentialRequest,
    request: Request,
    service: CredentialService = Depends(get_credential_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
) -> IssuedCredentialEnvelope:
    require_permission(principal.permissions, Permission.CREDENTIAL_MANAGE)
    expires_in = timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    try:
        rotated = await service.rotate(
            credential_id=credential_id,
            tenant_id=principal.tenant_id,
            name=payload.name,
            expires_in=expires_in,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
    await audit_service.record(
        tenant_id=principal.tenant_id,
        event_type=AuditEventType.CREDENTIAL_ROTATED,
        component="credential_management_api",
        action="rotate_credential",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={
            "revoked_credential_id": str(credential_id),
            "issued_credential_id": str(rotated.credential_id),
        },
    )
    return IssuedCredentialEnvelope(
        data=IssuedCredentialResponse.model_validate(rotated),
        meta=ResponseMeta(request_id=request_id(request)),
    )


@router.post("/{credential_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_credential(
    credential_id: UUID,
    request: Request,
    service: CredentialService = Depends(get_credential_service),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
) -> None:
    require_permission(principal.permissions, Permission.CREDENTIAL_MANAGE)
    try:
        await service.revoke(credential_id=credential_id, tenant_id=principal.tenant_id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
    except CredentialStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit_service.record(
        tenant_id=principal.tenant_id,
        event_type=AuditEventType.CREDENTIAL_REVOKED,
        component="credential_management_api",
        action="revoke_credential",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"revoked_credential_id": str(credential_id)},
    )
