from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from apps.api.paxli_api.config import Settings, get_settings
from apps.api.paxli_api.dependencies import (
    enforce_rate_limit,
    get_audit_service,
    get_decision_persistence_service,
    get_principal,
    get_rate_limiter,
    get_session_service,
    get_workflow_service,
)
from apps.api.paxli_api.schemas.verification import (
    CreateVerificationSessionRequest,
    DecisionProjection,
    ErrorEnvelope,
    PolicyReferenceResponse,
    ResponseMeta,
    SessionEnvelope,
    VerificationSessionResponse,
)
from core.audit.enums import AuditActorType, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.decision.models import DecisionProvenance
from core.decision.persistence import DecisionPersistenceService
from core.rate_limit.limiter import RateLimiterProtocol
from core.security.authentication import AuthenticatedPrincipal
from core.security.authorization import Permission, require_permission
from core.verification.enums import VerificationStatus
from core.verification.models import VerificationSession
from core.verification.service import (
    ConcurrentTransitionError,
    IdempotencyKeyReusedError,
    SessionAlreadyTerminalError,
    SessionNotFoundError,
    VerificationSessionService,
)
from core.verification.workflow import VerificationWorkflowService

router = APIRouter(prefix="/verification-sessions", tags=["verification-sessions"])


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", f"req_{uuid4().hex}")


def tenant_from_principal(principal: AuthenticatedPrincipal = Depends(get_principal)) -> str:
    return principal.tenant_id


def _decision_projection(decision: DecisionProvenance) -> DecisionProjection:
    return DecisionProjection(
        outcome=decision.outcome,
        reason_codes=decision.reason_codes,
        policy=PolicyReferenceResponse(
            id=decision.policy_reference.policy_id,
            version=decision.policy_reference.policy_version,
            hash=decision.policy_reference.policy_hash,
        ),
    )


def _session_envelope(
    session: VerificationSession, decision: DecisionProvenance | None, request: Request
) -> SessionEnvelope:
    """WF-001 §9: the read-time DecisionResult projection, attached here
    rather than through VerificationSessionResponse.model_validate(session)
    alone -- session never carries a `.decision` attribute of its own
    (never a denormalized column), so the projection is always supplied
    by the caller, which already knows whether/which decision applies."""
    response = VerificationSessionResponse.model_validate(session)
    if decision is not None:
        response = response.model_copy(update={"decision": _decision_projection(decision)})
    return SessionEnvelope(data=response, meta=ResponseMeta(request_id=request_id(request)))


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
    try:
        session = await service.create(
            tenant_id=principal.tenant_id,
            external_reference=payload.external_reference,
            assurance_level=payload.assurance_level,
            idempotency_key=idempotency_key,
        )
    except IdempotencyKeyReusedError as exc:
        # WF-001 §10 / WF-4.9.3: materially different reuse of the same
        # Idempotency-Key, never silently resolved to the first write.
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used for a materially different request",
        ) from exc
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
    return _session_envelope(session, None, request)


@router.get(
    "/{session_id}",
    response_model=SessionEnvelope,
    responses={404: {"model": ErrorEnvelope}},
)
async def get_session(
    session_id: UUID,
    request: Request,
    service: VerificationSessionService = Depends(get_session_service),  # noqa: B008
    decision_service: DecisionPersistenceService = Depends(  # noqa: B008
        get_decision_persistence_service
    ),
    audit_service: AuditService = Depends(get_audit_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
) -> SessionEnvelope:
    require_permission(principal, Permission.VERIFICATION_READ, session_id=str(session_id))
    try:
        session = await service.get(session_id=session_id, tenant_id=principal.tenant_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    # WF-001 §9: populated if and only if COMPLETED, never a partial or
    # speculative decision for any other status.
    decision = None
    if session.status is VerificationStatus.COMPLETED:
        decision = await decision_service.get_for_session(
            session_id=session_id, tenant_id=principal.tenant_id
        )
        if decision is None:
            # Should be unreachable: the only path to COMPLETED
            # (VerificationWorkflowService.submit()) always persists a
            # decision first. Surfacing this loudly rather than returning
            # a silently incomplete result (DEC-5.24.1's "never mask an
            # unresolved state" discipline).
            raise RuntimeError(
                f"session_id={session_id!s} is COMPLETED but has no persisted decision"
            )
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
    return _session_envelope(session, decision, request)


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
    except SessionAlreadyTerminalError as exc:
        raise HTTPException(
            status_code=409, detail="Verification session has already reached a terminal state"
        ) from exc
    except ConcurrentTransitionError as exc:
        # WF-001 §6: an explicit, client-intent-driven request racing a
        # concurrent transition is a real conflict to surface, not a
        # harmless side effect to swallow (unlike the lazy expire check
        # inside VerificationSessionService.get()).
        raise HTTPException(
            status_code=409, detail="Verification session state changed concurrently"
        ) from exc
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
    return _session_envelope(session, None, request)


@router.post(
    "/{session_id}/submit",
    response_model=SessionEnvelope,
    responses={404: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
)
async def submit_session(
    session_id: UUID,
    request: Request,
    workflow_service: VerificationWorkflowService = Depends(get_workflow_service),  # noqa: B008
    principal: AuthenticatedPrincipal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
) -> SessionEnvelope:
    """WF-001 §2-4/§12: the one public trigger for processing. Safe to
    call (or retry) from any status -- VerificationWorkflowService.submit()
    dispatches on the session's current status, so a client retry, a
    still-CAPTURING session, or an already-COMPLETED one all converge to
    the same correct response. No Idempotency-Key: §4's own dispatch,
    not a separate fingerprint mechanism, is the idempotency guarantee
    here. All four lifecycle audit events (§13) are recorded inside
    submit() itself -- nothing further to record at this layer."""
    require_permission(principal, Permission.VERIFICATION_SUBMIT, session_id=str(session_id))
    # Operational endpoint class -> fail_mode="open" (Foundation-010
    # review guardrail #2): a limiter outage must not itself block
    # verification processing, the same reasoning as session creation
    # and evidence submission.
    await enforce_rate_limit(
        principal,
        operation="verification_submit",
        limit=settings.rate_limit_verification_submit_per_window,
        window_seconds=settings.rate_limit_verification_submit_window_seconds,
        fail_mode="open",
        limiter=limiter,
    )
    try:
        session, decision = await workflow_service.submit(
            session_id=session_id,
            tenant_id=principal.tenant_id,
            request_id=request_id(request),
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Verification session not found") from exc
    except SessionAlreadyTerminalError as exc:
        raise HTTPException(
            status_code=409, detail="Verification session has already reached a terminal state"
        ) from exc
    return _session_envelope(session, decision, request)
