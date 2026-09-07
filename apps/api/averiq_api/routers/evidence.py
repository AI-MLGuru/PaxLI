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

from apps.api.averiq_api.dependencies import get_audit_service, get_evidence_service
from apps.api.averiq_api.routers.verification_sessions import request_id, tenant_header
from apps.api.averiq_api.schemas.verification import (
    EvidenceListEnvelope,
    EvidenceResponse,
    ResponseMeta,
)
from core.audit.enums import AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.evidence.enums import EvidenceType
from core.evidence.service import EvidenceService
from core.verification.service import SessionExpiredError, SessionNotFoundError

router = APIRouter(prefix="/verification-sessions", tags=["evidence"])


async def store_upload(
    *,
    session_id: UUID,
    evidence_type: EvidenceType,
    request: Request,
    file: UploadFile,
    service: EvidenceService,
    tenant_id: str,
    idempotency_key: str | None,
    audit_service: AuditService,
) -> EvidenceResponse:
    settings = request.app.state.settings
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
            mime_type=file.content_type or "application/octet-stream",
            checksum=sha256(content).hexdigest(),
            metadata={"filename": file.filename} if file.filename else {},
            idempotency_key=idempotency_key,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    except SessionExpiredError as exc:
        raise HTTPException(status_code=409, detail="Verification session is not active") from exc
    await audit_service.record(
        tenant_id=tenant_id,
        session_id=session_id,
        event_type=AuditEventType.EVIDENCE_UPLOADED,
        component="evidence_api",
        action="upload_evidence",
        status=AuditStatus.SUCCESS,
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
    tenant_id: str = Depends(tenant_header),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    return await store_upload(
        session_id=session_id,
        evidence_type=EvidenceType.SELFIE,
        request=request,
        file=file,
        service=service,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        audit_service=audit_service,
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
    tenant_id: str = Depends(tenant_header),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    return await store_upload(
        session_id=session_id,
        evidence_type=EvidenceType.DOCUMENT,
        request=request,
        file=file,
        service=service,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        audit_service=audit_service,
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
    tenant_id: str = Depends(tenant_header),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> EvidenceResponse:
    return await store_upload(
        session_id=session_id,
        evidence_type=EvidenceType.LIVENESS,
        request=request,
        file=file,
        service=service,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        audit_service=audit_service,
    )


@router.get("/{session_id}/evidence", response_model=EvidenceListEnvelope)
async def list_evidence(
    session_id: UUID,
    request: Request,
    service: EvidenceService = Depends(get_evidence_service),  # noqa: B008
    tenant_id: str = Depends(tenant_header),  # noqa: B008
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
) -> EvidenceListEnvelope:
    try:
        evidence = await service.list(session_id=session_id, tenant_id=tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    await audit_service.record(
        tenant_id=tenant_id,
        session_id=session_id,
        event_type=AuditEventType.EVIDENCE_RETRIEVED,
        component="evidence_api",
        action="list_evidence",
        status=AuditStatus.SUCCESS,
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"count": len(evidence)},
    )
    return EvidenceListEnvelope(
        data=[EvidenceResponse.model_validate(item) for item in evidence],
        meta=ResponseMeta(request_id=request_id(request)),
    )
