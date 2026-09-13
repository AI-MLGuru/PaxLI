from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.paxli_api.config import Settings, get_settings
from apps.api.paxli_api.dependencies import (
    enforce_rate_limit,
    get_evidence_result_service,
    get_principal,
    get_rate_limiter,
)
from apps.api.paxli_api.routers.verification_sessions import request_id
from apps.api.paxli_api.schemas.verification import DeleteEvidenceRequest
from core.deletion.exceptions import InvalidDeletionRequestError
from core.evidence_result.exceptions import EvidenceResultNotFoundError
from core.evidence_result.service import EvidenceResultService
from core.rate_limit.limiter import RateLimiterProtocol
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission
from infrastructure.database.session import get_db_session

router = APIRouter(prefix="/management/evidence-results", tags=["management-evidence-results"])


@router.delete("/{evidence_result_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence_result(
    evidence_result_id: UUID,
    payload: DeleteEvidenceRequest,
    request: Request,
    service: EvidenceResultService = Depends(get_evidence_result_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> None:
    """Evidence-result deletion boundary (Invariant-06 remediation Phase 4).
    A management-scoped route, not session-nested: unlike raw evidence,
    evidence results have no existing session-relative HTTP surface at all
    (no GET/list endpoint is wired up yet either) -- this endpoint governs
    only the deletion lifecycle, the one capability explicitly in scope.

    Same two-phase, synchronous-within-one-request shape as
    DELETE /verification-sessions/{session_id}/evidence/{evidence_id} --
    including the same explicit commit of the ambient session between the
    two phases, required because Phase 2's reconciler opens its own
    independent connection via session_factory and can only see Phase 1's
    tombstone once it is genuinely committed, not merely flushed. See that
    route's docstring for the full explanation."""
    require_permission(principal, Permission.EVIDENCE_DELETE)
    await enforce_rate_limit(
        principal,
        operation="evidence_result_delete",
        limit=settings.rate_limit_credential_manage_per_window,
        window_seconds=settings.rate_limit_credential_manage_window_seconds,
        fail_mode="closed",
        limiter=limiter,
    )
    try:
        await service.request_deletion(
            evidence_result_id=evidence_result_id,
            tenant_id=principal.tenant_id,
            deletion_basis=payload.deletion_basis,
            basis_reference=payload.basis_reference,
            authorized_by=str(principal.credential_id),
            request_id=request_id(request),
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
    except EvidenceResultNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Evidence result not found") from exc
    except InvalidDeletionRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db_session.commit()
    await service.reconcile_deletion(
        evidence_result_id=evidence_result_id,
        tenant_id=principal.tenant_id,
        request_id=request_id(request),
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
