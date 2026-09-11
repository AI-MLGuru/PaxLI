from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from apps.api.paxli_api.config import Settings, get_settings
from apps.api.paxli_api.dependencies import (
    enforce_rate_limit,
    get_audit_service,
    get_credential_service,
    get_principal,
    get_rate_limiter,
)
from apps.api.paxli_api.routers.verification_sessions import request_id
from apps.api.paxli_api.schemas.security import (
    IssueCredentialRequest,
    IssuedCredentialEnvelope,
    IssuedCredentialResponse,
    RotateCredentialRequest,
)
from apps.api.paxli_api.schemas.verification import ResponseMeta
from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.rate_limit.limiter import RateLimiterProtocol
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
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IssuedCredentialEnvelope:
    require_permission(principal, Permission.CREDENTIAL_MANAGE)
    # Security-critical endpoint class -> fail_mode="closed" (Foundation-010
    # review guardrail #2/#3): a limiter outage rejects rather than silently
    # admitting unbounded credential-management traffic.
    await enforce_rate_limit(
        principal,
        operation="credential_manage",
        limit=settings.rate_limit_credential_manage_per_window,
        window_seconds=settings.rate_limit_credential_manage_window_seconds,
        fail_mode="closed",
        limiter=limiter,
    )
    expires_in = timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    issued = await service.issue(
        tenant_id=principal.tenant_id,
        name=payload.name,
        scope=payload.scope,
        expires_in=expires_in,
        idempotency_key=idempotency_key,
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
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IssuedCredentialEnvelope:
    require_permission(principal, Permission.CREDENTIAL_MANAGE)
    await enforce_rate_limit(
        principal,
        operation="credential_manage",
        limit=settings.rate_limit_credential_manage_per_window,
        window_seconds=settings.rate_limit_credential_manage_window_seconds,
        fail_mode="closed",
        limiter=limiter,
    )
    expires_in = timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    try:
        rotated = await service.rotate(
            credential_id=credential_id,
            tenant_id=principal.tenant_id,
            name=payload.name,
            expires_in=expires_in,
            idempotency_key=idempotency_key,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
    except CredentialStateError as exc:
        # rotate() revokes the existing credential internally, so the same
        # already-expired-but-not-revoked state can surface here too --
        # previously unhandled (a latent 500), now routed the same way as
        # revoke_credential (Invariant-12 remediation 2).
        exc.actor_id = str(principal.credential_id)
        raise
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
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
) -> None:
    require_permission(principal, Permission.CREDENTIAL_MANAGE)
    await enforce_rate_limit(
        principal,
        operation="credential_manage",
        limit=settings.rate_limit_credential_manage_per_window,
        window_seconds=settings.rate_limit_credential_manage_window_seconds,
        fail_mode="closed",
        limiter=limiter,
    )
    try:
        await service.revoke(credential_id=credential_id, tenant_id=principal.tenant_id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=404, detail="Credential not found") from exc
    except CredentialStateError as exc:
        # The service layer knows the target credential/tenant but not who
        # is attempting the operation; fill in the actor here (the router
        # is the only layer with `principal`) and let main.py's global
        # handler record the required CREDENTIAL_OPERATION_FAILED audit
        # event in its own independent transaction before returning 409
        # (Invariant-12 remediation 2).
        exc.actor_id = str(principal.credential_id)
        raise
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
