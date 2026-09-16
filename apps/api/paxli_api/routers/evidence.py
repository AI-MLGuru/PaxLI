from hashlib import sha256
from time import perf_counter
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
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.paxli_api.config import Settings, get_settings
from apps.api.paxli_api.dependencies import (
    enforce_rate_limit,
    get_audit_service,
    get_evidence_service,
    get_principal,
    get_rate_limiter,
)
from apps.api.paxli_api.routers.verification_sessions import request_id
from apps.api.paxli_api.schemas.verification import (
    DeleteEvidenceRequest,
    EvidenceListEnvelope,
    EvidenceResponse,
    ResponseMeta,
)
from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.deletion.exceptions import InvalidDeletionRequestError
from core.evidence.enums import EvidenceType
from core.evidence.media_validation import UnsupportedMediaError
from core.evidence.service import (
    EvidenceDeletedError,
    EvidenceNotFoundError,
    EvidenceService,
    IdempotencyKeyReusedError,
)
from core.rate_limit.limiter import RateLimiterProtocol
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission
from core.verification.service import SessionExpiredError, SessionNotFoundError
from infrastructure.database.session import get_db_session
from infrastructure.observability.stage_logging import log_stage_event

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
    rate_limit_checked: bool = False,
) -> EvidenceResponse:
    require_permission(principal, Permission.EVIDENCE_SUBMIT, session_id=str(session_id))
    tenant_id = principal.tenant_id
    settings = request.app.state.settings
    # Operational endpoint class -> fail_mode="open" (Foundation-010 review
    # guardrail #2: bypasses the limiter only, never authentication/
    # authorization, which already ran above).
    if not rate_limit_checked:
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
    except IdempotencyKeyReusedError as exc:
        # WF-001 §10 / WF-4.9.3: materially different reuse of the same
        # Idempotency-Key, never silently resolved to the first write.
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used for a materially different request",
        ) from exc
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
    frames: Annotated[list[UploadFile], File(...)],
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    require_permission(principal, Permission.EVIDENCE_SUBMIT, session_id=str(session_id))
    settings = request.app.state.settings
    await enforce_rate_limit(
        principal,
        operation="evidence_submit",
        limit=settings.rate_limit_evidence_submit_per_window,
        window_seconds=settings.rate_limit_evidence_submit_window_seconds,
        fail_mode="open",
        limiter=limiter,
    )
    if not frames or len(frames) > settings.liveness_max_frames:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Temporal Liveness Demo requires 1 to {settings.liveness_max_frames} frames",
        )
    started_at = perf_counter()
    log_stage_event(
        "verification_stage_started",
        stage="liveness_capture",
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        session_id=str(session_id),
        frame_count=len(frames),
    )
    uploaded: EvidenceResponse | None = None
    try:
        for index, frame in enumerate(frames):
            frame_key = f"{idempotency_key}:frame:{index}" if idempotency_key else None
            uploaded = await store_upload(
                session_id=session_id,
                evidence_type=EvidenceType.LIVENESS,
                request=request,
                file=frame,
                service=service,
                principal=principal,
                idempotency_key=frame_key,
                audit_service=audit_service,
                limiter=limiter,
                rate_limit_checked=True,
            )
    except Exception:
        log_stage_event(
            "verification_stage_failed",
            stage="liveness_capture",
            request_id=request_id(request),
            correlation_id=request.headers.get("X-Correlation-ID"),
            session_id=str(session_id),
            duration_ms=(perf_counter() - started_at) * 1000,
            frame_count=len(frames),
            failure_category="capture_processing_failed",
        )
        raise
    assert uploaded is not None
    log_stage_event(
        "verification_stage_completed",
        stage="liveness_capture",
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        session_id=str(session_id),
        duration_ms=(perf_counter() - started_at) * 1000,
        frame_count=len(frames),
    )
    return uploaded


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


@router.get("/{session_id}/evidence/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    session_id: UUID,
    evidence_id: UUID,
    request: Request,
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
) -> EvidenceResponse:
    """Individual evidence retrieval (Invariant-06 remediation Phase 4).
    Tombstone existence is checked BEFORE the live row, and regardless of
    executed_at -- once deletion has been durably requested, this endpoint
    must stop serving the resource as live (EvidenceDeletedError -> 410,
    handled globally so the response body carries no deletion metadata).
    A resource belonging to another tenant, or never created at all, is an
    ordinary 404 -- indistinguishable from "never existed" (never a
    cross-tenant existence oracle)."""
    require_permission(principal, Permission.EVIDENCE_READ, session_id=str(session_id))
    tombstone = await service.get_tombstone(evidence_id=evidence_id, tenant_id=principal.tenant_id)
    if tombstone is not None and tombstone.session_id == session_id:
        raise EvidenceDeletedError
    evidence = await service.get(evidence_id=evidence_id, tenant_id=principal.tenant_id)
    if evidence is None or evidence.session_id != session_id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    await audit_service.record(
        tenant_id=principal.tenant_id,
        session_id=session_id,
        event_type=AuditEventType.EVIDENCE_RETRIEVED,
        component="evidence_api",
        action="get_evidence",
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.CLIENT,
        actor_id=str(principal.credential_id),
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"evidence_id": str(evidence_id)},
    )
    return EvidenceResponse.model_validate(evidence)


@router.delete("/{session_id}/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence(
    session_id: UUID,
    evidence_id: UUID,
    payload: DeleteEvidenceRequest,
    request: Request,
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    """Two-phase deletion (Invariant-06 remediation), driven synchronously
    within this one request since no worker/queue exists in v1: request_
    deletion (Phase 1, durable intent + REQUIRED audit) followed by
    reconcile_deletion (Phase 2, its own independent transaction opened via
    session_factory). Phase 2's independent session can only see Phase 1's
    tombstone once it is actually committed, not merely flushed on the
    ambient session -- so this route explicitly commits the ambient
    session (the same db_session get_evidence_service's own EvidenceService
    was built on, via FastAPI's dependency cache) between the two phases,
    rather than leaving that commit to the request-scoped get_db_session
    dependency, which would otherwise only commit AFTER reconcile_deletion
    has already run and failed. Confirmed live against a real
    multi-connection database (not merely assumed): the ambient session and
    the reconciler's session are genuinely separate connections, so without
    this explicit commit Phase 2 always raised TombstoneNotFoundError --
    masked only by a test fixture that, until fixed, accidentally shared a
    single physical SQLite connection across both. If Phase 2 raises after
    this commit, Phase 1's tombstone already durably stands -- the client
    sees an error but a retried DELETE safely resumes from the tombstone
    via each phase's idempotent short-circuit, never re-doing completed
    work or setting executed_at prematurely.

    Administrative-only (Permission.EVIDENCE_DELETE); reuses the
    credential-management rate-limit bucket under a distinct operation
    name rather than adding a new Settings knob for a single admin route."""
    require_permission(principal, Permission.EVIDENCE_DELETE, session_id=str(session_id))
    await enforce_rate_limit(
        principal,
        operation="evidence_delete",
        limit=settings.rate_limit_credential_manage_per_window,
        window_seconds=settings.rate_limit_credential_manage_window_seconds,
        fail_mode="closed",
        limiter=limiter,
    )
    try:
        tombstone = await service.request_deletion(
            evidence_id=evidence_id,
            tenant_id=principal.tenant_id,
            deletion_basis=payload.deletion_basis,
            basis_reference=payload.basis_reference,
            authorized_by=str(principal.credential_id),
            request_id=request_id(request),
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evidence not found") from exc
    except InvalidDeletionRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if tombstone.session_id != session_id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    await db_session.commit()
    await service.reconcile_deletion(
        evidence_id=evidence_id,
        tenant_id=principal.tenant_id,
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
