from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from apps.api.averiq_api.dependencies import (
    enforce_rate_limit,
    get_audit_service,
    get_evidence_service,
    get_principal,
    get_rate_limiter,
)
from apps.api.averiq_api.routers.verification_sessions import request_id
from apps.api.averiq_api.schemas.verification import (
    EvidenceListEnvelope,
    EvidenceResponse,
    ResponseMeta,
)
from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.evidence.enums import EvidenceType
from core.evidence.media_validation import UnsupportedMediaError
from core.evidence.service import EvidenceService
from core.rate_limit.limiter import RateLimiterProtocol
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission
from core.verification.service import SessionExpiredError, SessionNotFoundError

router = APIRouter(prefix="/verification-sessions", tags=["evidence"])


async def store_upload(
    *,
    session_id: UUID,
    evidence_type: EvidenceType,
    request: Request,
    file: UploadFile,
    service: EvidenceService,
    principal: AuthenticatedPrincipal,
    idempotency_key: str | None,
    audit_service: AuditService,
    limiter: RateLimiterProtocol,
) -> EvidenceResponse:
    require_permission(principal, Permission.EVIDENCE_SUBMIT, session_id=str(session_id))
    tenant_id = principal.tenant_id
    settings = request.app.state.settings
    # Operational endpoint class -> fail_mode="open" (Foundation-010 review
    # guardrail #2: bypasses the limiter only, never authentication/
    # authorization, which already ran above).
    await enforce_rate_limit(
        principal,
        operation="evidence_submit",
        limit=settings.rate_limit_evidence_submit_per_window,
        window_seconds=settings.rate_limit_evidence_submit_window_seconds,
        fail_mode="open",
        limiter=limiter,
    )
    content = await file.read(settings.evidence_max_bytes + 1)
    if len(content) > settings.evidence_max_bytes:
        raise HTTPException(status_code=413, detail="Evidence file is too large")
    if not content:
        raise HTTPException(status_code=400, detail="Evidence file is empty")
    try:
        evidence = await service.add(
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=evidence_type,
            content=content,
            checksum=sha256(content).hexdigest(),
            metadata={"filename": file.filename} if file.filename else {},
            idempotency_key=idempotency_key,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=409, detail="Verification session is not active") from exc
    except UnsupportedMediaError as exc:
        raise HTTPException(
            status_code=415, detail="Unsupported or unrecognized file format"
        ) from exc
    await audit_service.record(
        tenant_id=tenant_id,
        session_id=session_id,
        event_type=AuditEventType.EVIDENCE_UPLOADED,
        component="evidence_api",
        action="upload_evidence",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={
            "evidence_type": evidence_type.value,
            "size_bytes": evidence.size_bytes,
        },
        dedupe_key=f"evidence-upload:{evidence.id}",
    )
    return EvidenceResponse.model_validate(evidence)


@router.post(
    "/{session_id}/selfie",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_selfie(
    session_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File(...)],
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    return await store_upload(
        session_id=session_id,
        evidence_type=EvidenceType.SELFIE,
        request=request,
        file=file,
        service=service,
        principal=principal,
        idempotency_key=idempotency_key,
        audit_service=audit_service,
        limiter=limiter,
    )


@router.post(
    "/{session_id}/document",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    session_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File(...)],
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    return await store_upload(
        session_id=session_id,
        evidence_type=EvidenceType.DOCUMENT,
        request=request,
        file=file,
        service=service,
        principal=principal,
        idempotency_key=idempotency_key,
        audit_service=audit_service,
        limiter=limiter,
    )


@router.post(
    "/{session_id}/liveness",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_liveness(
    session_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File(...)],
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    return await store_upload(
        session_id=session_id,
        evidence_type=EvidenceType.LIVENESS,
        request=request,
        file=file,
        service=service,
        principal=principal,
        idempotency_key=idempotency_key,
        audit_service=audit_service,
        limiter=limiter,
    )


@router.get("/{session_id}/evidence", response_model=EvidenceListEnvelope)
async def list_evidence(
    session_id: UUID,
    request: Request,
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
) -> EvidenceListEnvelope:
    require_permission(principal, Permission.EVIDENCE_READ, session_id=str(session_id))
    try:
        evidence = await service.list(session_id=session_id, tenant_id=principal.tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    await audit_service.record(
        tenant_id=principal.tenant_id,
        session_id=session_id,
        event_type=AuditEventType.EVIDENCE_RETRIEVED,
        component="evidence_api",
        action="list_evidence",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"count": len(evidence)},
    )
    return EvidenceListEnvelope(
        data=[EvidenceResponse.model_validate(item) for item in evidence],
        meta=ResponseMeta(request_id=request_id(request)),
    )
