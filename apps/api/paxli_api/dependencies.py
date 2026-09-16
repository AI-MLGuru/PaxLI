from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request
from insightface.app import FaceAnalysis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.paxli_api.config import Settings, get_settings
from core.audit.service import AuditService
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.document.deterministic import (
    DeterministicBarcodeDecoder,
    DeterministicDocumentClassifier,
    DeterministicFieldReconciler,
    DeterministicMRZParser,
    DeterministicQualityAssessor,
)
from core.evidence.service import EvidenceService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.face.matcher import CosineFaceMatcher
from core.policy.service import PolicyService
from core.rate_limit.enums import RateLimitScope
from core.rate_limit.evaluation import FailMode, evaluate_admission
from core.rate_limit.keys import build_scope_key
from core.rate_limit.limiter import RateLimiterProtocol
from core.rate_limit.metrics import RateLimitMetrics
from core.security.authentication import AuthenticatedPrincipal, authenticate_bearer
from core.security.credentials import CredentialService
from core.verification.service import VerificationSessionService
from core.verification.workflow import VerificationWorkflowService
from infrastructure.database.repositories.audit_event import (
    SqlAlchemyAuditEventRepository,
)
from infrastructure.database.repositories.credential import SqlAlchemyCredentialStore
from infrastructure.database.repositories.decision import SqlAlchemyDecisionRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import get_db_session, session_factory
from infrastructure.deletion.reconciliation import (
    SqlAlchemyEvidenceDeletionReconciler,
    SqlAlchemyEvidenceResultDeletionReconciler,
)
from infrastructure.document.paddle_ocr_engine import PaddleOCREngine
from infrastructure.document.processor import SqlAlchemyDocumentProcessor
from infrastructure.face.document_face_extractor import InsightFaceDocumentFaceExtractor
from infrastructure.face.document_reference_resolver import DocumentBoundReferenceResolver
from infrastructure.face.insightface_adapter import (
    InsightFaceDetector,
    InsightFaceEmbedder,
    InsightFaceQualityAssessor,
)
from infrastructure.face.processor import BiometricProcessor
from infrastructure.rate_limit.network_source import (
    get_network_source_hmac_key,
    hash_network_source,
)
from infrastructure.rate_limit.postgres_limiter import PostgresRateLimiter
from infrastructure.rate_limit.rules import authenticated_rules, pre_auth_rule
from infrastructure.security.hashing import ScryptSecretHasher
from infrastructure.security.local_key_provider import get_local_key_provider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.interface import ObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

# Module-level, not request-scoped: PostgresRateLimiter is stateless besides
# holding the session factory, and RateLimitMetrics is meant to accumulate
# across requests (same pattern as core.reliability.metrics.ReliabilityMetrics
# instances in main.py).
_RATE_LIMITER = PostgresRateLimiter(session_factory)
RATE_LIMIT_METRICS = RateLimitMetrics()

_paddle_ocr_engine: PaddleOCREngine | None = None


def _get_paddle_ocr_engine() -> PaddleOCREngine:
    """Lazy module-level singleton, same shape as apps.api.paxli_api.main.
    _get_health_minio_client(): PaddleOCREngine's underlying model load is
    expensive (a multi-second cold start, BD-001 Slice A) and MUST NOT
    happen per request. Lazy rather than constructed at import time so
    merely importing this module -- including from tests that never
    exercise document processing -- doesn't pay that cost."""
    global _paddle_ocr_engine
    if _paddle_ocr_engine is None:
        _paddle_ocr_engine = PaddleOCREngine()
    return _paddle_ocr_engine


_shared_detection_face_analysis: FaceAnalysis | None = None
_embedder_face_analysis: FaceAnalysis | None = None


def _get_shared_detection_face_analysis() -> FaceAnalysis:
    """Lazy module-level singleton, same shape as _get_paddle_ocr_engine()
    above. BD-001.10 I-1: one detection-only FaceAnalysis instance shared
    by FaceDetector, FaceQualityAssessor, and DocumentFaceExtractor --
    empirically confirmed safe under concurrent asyncio.to_thread calls,
    and confirmed to preserve each of those three capabilities' own
    ~1-2s steady-state latency (never dragged onto the materially slower
    recognition execution path measured for allowed_modules including
    "recognition"). The module-level variable is assigned only after
    FaceAnalysis(...) and .prepare() both succeed -- a failed first
    attempt leaves it at None, so the next call retries from scratch,
    the same retry-safety property _get_paddle_ocr_engine() already has."""
    global _shared_detection_face_analysis
    if _shared_detection_face_analysis is None:
        app = FaceAnalysis(
            name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection"]
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _shared_detection_face_analysis = app
    return _shared_detection_face_analysis


def _get_embedder_face_analysis() -> FaceAnalysis:
    """Lazy module-level singleton. BD-001.10 I-1: a separate
    detection+recognition FaceAnalysis instance, used only by
    FaceEmbedder -- deliberately not merged into the shared
    detection-only instance above, since doing so would force the
    other three detection-only capabilities onto the materially slower
    recognition execution path for no benefit to any of them (confirmed
    by live benchmark, not assumed)."""
    global _embedder_face_analysis
    if _embedder_face_analysis is None:
        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _embedder_face_analysis = app
    return _embedder_face_analysis


async def get_session_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[VerificationSessionService]:
    policy_service = PolicyService(
        SqlAlchemyVerificationPolicyRepository(db_session),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        EvidenceResultSchemaCatalog(),
    )
    yield VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(db_session),
        audit_service=AuditService(SqlAlchemyAuditEventRepository(db_session)),
        policy_service=policy_service,
        session_ttl_minutes=settings.session_ttl_minutes,
    )


async def get_evidence_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[EvidenceService]:
    session_repository = SqlAlchemyVerificationSessionRepository(db_session)
    key_provider = get_local_key_provider(
        key_id=settings.evidence_encryption_key_id,
        encoded_key=settings.evidence_encryption_key,
    )
    storage = EncryptedObjectStorage(
        MinioObjectStorage(settings), key_provider, settings.evidence_encryption_key_id
    )
    yield EvidenceService(
        SqlAlchemyEvidenceRepository(db_session),
        VerificationSessionService(
            session_repository,
            audit_service=AuditService(SqlAlchemyAuditEventRepository(db_session)),
            session_ttl_minutes=settings.session_ttl_minutes,
        ),
        storage,
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        deletion_reconciler=SqlAlchemyEvidenceDeletionReconciler(session_factory, storage),
    )


async def get_evidence_result_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[EvidenceResultService]:
    key_provider = get_local_key_provider(
        key_id=settings.evidence_encryption_key_id,
        encoded_key=settings.evidence_encryption_key,
    )
    yield EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(
            db_session, key_provider, settings.evidence_encryption_key_id
        ),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        SqlAlchemyEvidenceRepository(db_session),
        deletion_reconciler=SqlAlchemyEvidenceResultDeletionReconciler(
            session_factory, key_provider, settings.evidence_encryption_key_id
        ),
    )


async def get_decision_persistence_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncIterator[DecisionPersistenceService]:
    """A standalone, read-mostly provider -- WF-001 §9's session GET
    decision projection needs only DecisionPersistenceService.
    get_for_session(), never the heavier DecisionOrchestrator (which
    pulls in PolicyService/EvidenceResultService for evaluation this
    pure read never performs)."""
    yield DecisionPersistenceService(
        SqlAlchemyDecisionRepository(db_session),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
    )


def get_object_storage(settings: Settings = Depends(get_settings)) -> ObjectStorage:  # noqa: B008
    """A real `Depends()`-resolvable seam over the encrypted-MinIO storage
    construction `get_evidence_service` also builds inline -- needed here
    (unlike there) because nothing overrides `get_workflow_service` at the
    function level in tests, so anything it builds directly bypasses test
    overrides entirely. Same rationale as get_session_factory below."""
    key_provider = get_local_key_provider(
        key_id=settings.evidence_encryption_key_id,
        encoded_key=settings.evidence_encryption_key,
    )
    return EncryptedObjectStorage(
        MinioObjectStorage(settings), key_provider, settings.evidence_encryption_key_id
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """A real `Depends()`-resolvable seam over the module-level
    `session_factory` sessionmaker -- unlike a plain imported name (which
    `app.dependency_overrides` cannot intercept, since that mechanism only
    ever substitutes things resolved through FastAPI's own dependency
    graph), this can be swapped for a test-scoped sessionmaker the same
    way get_db_session already is. Needed by anything that -- like
    DocumentProcessor -- must open its OWN independent sessions beyond
    the single ambient per-request one (DP-001 Decision 4), so its
    backend stays consistent with whatever get_db_session was overridden
    to, rather than silently talking to a different database entirely."""
    return session_factory


async def get_workflow_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    request_session_factory: async_sessionmaker[AsyncSession] = Depends(  # noqa: B008
        get_session_factory
    ),
    document_storage: ObjectStorage = Depends(get_object_storage),  # noqa: B008
) -> AsyncIterator[VerificationWorkflowService]:
    policy_service = PolicyService(
        SqlAlchemyVerificationPolicyRepository(db_session),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        EvidenceResultSchemaCatalog(),
    )
    session_service = VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(db_session),
        audit_service=AuditService(SqlAlchemyAuditEventRepository(db_session)),
        policy_service=policy_service,
        session_ttl_minutes=settings.session_ttl_minutes,
    )
    key_provider = get_local_key_provider(
        key_id=settings.evidence_encryption_key_id,
        encoded_key=settings.evidence_encryption_key,
    )
    evidence_result_service = EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(
            db_session, key_provider, settings.evidence_encryption_key_id
        ),
        AuditService(SqlAlchemyAuditEventRepository(db_session)),
        SqlAlchemyEvidenceRepository(db_session),
    )
    audit_service = AuditService(SqlAlchemyAuditEventRepository(db_session))
    persistence_service = DecisionPersistenceService(
        SqlAlchemyDecisionRepository(db_session), audit_service
    )
    orchestrator = DecisionOrchestrator(
        session_service, policy_service, evidence_result_service, persistence_service, audit_service
    )
    document_processor = SqlAlchemyDocumentProcessor(
        request_session_factory,
        key_provider,
        settings.evidence_encryption_key_id,
        document_storage,
        DeterministicQualityAssessor(),
        DeterministicDocumentClassifier(),
        DeterministicMRZParser(),
        DeterministicBarcodeDecoder(),
        _get_paddle_ocr_engine(),
        DeterministicFieldReconciler(),
    )
    detection_app = _get_shared_detection_face_analysis()
    embedder_app = _get_embedder_face_analysis()
    reference_source = DocumentBoundReferenceResolver(
        request_session_factory,
        key_provider,
        settings.evidence_encryption_key_id,
        document_storage,
        InsightFaceDocumentFaceExtractor(app=detection_app),
    )
    biometric_processor = BiometricProcessor(
        request_session_factory,
        key_provider,
        settings.evidence_encryption_key_id,
        document_storage,
        InsightFaceDetector(app=detection_app),
        InsightFaceQualityAssessor(app=detection_app),
        InsightFaceEmbedder(app=embedder_app),
        CosineFaceMatcher(),
        reference_source,
    )
    yield VerificationWorkflowService(
        session_service, orchestrator, audit_service, document_processor, biometric_processor
    )


async def get_audit_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncIterator[AuditService]:
    yield AuditService(SqlAlchemyAuditEventRepository(db_session))


async def get_credential_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncIterator[CredentialService]:
    yield CredentialService(SqlAlchemyCredentialStore(db_session), ScryptSecretHasher())


def get_rate_limiter() -> RateLimiterProtocol:
    return _RATE_LIMITER


async def enforce_pre_auth_admission(
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),  # noqa: B008
) -> None:
    """Runs BEFORE authenticate_bearer()'s credential lookup -- wired as a
    sub-dependency of get_principal below, which is the only way to
    guarantee this executes before authenticate_bearer is ever called
    (FastAPI resolves every Depends() of a function before invoking that
    function's own body). SEC-7.32's credential-attack surface must never
    reach the expensive scrypt/credential-lookup path once throttled
    (Foundation-010 discovery). Fail-closed: this is the security-critical
    endpoint class."""
    client_host = request.client.host if request.client is not None else "unknown"
    hmac_key = get_network_source_hmac_key(
        key_id=settings.rate_limit_network_source_hmac_key_id,
        encoded_key=settings.rate_limit_network_source_hmac_key,
    )
    network_source_key = hash_network_source(
        client_host,
        key_id=settings.rate_limit_network_source_hmac_key_id,
        key=hmac_key,
    )
    scope_key = build_scope_key(
        RateLimitScope.NETWORK_SOURCE, "authenticate", network_source_key=network_source_key
    )
    rule = pre_auth_rule(
        limit=settings.rate_limit_auth_attempts_per_window,
        window_seconds=settings.rate_limit_auth_window_seconds,
    )
    await evaluate_admission(
        rules_and_keys=[(rule, scope_key)],
        limiter=limiter,
        fail_mode="closed",
        metrics=RATE_LIMIT_METRICS,
    )


async def get_principal(
    authorization: str | None = Header(default=None),
    credential_service: CredentialService = Depends(get_credential_service),  # noqa: B008
    _pre_auth_admission: None = Depends(enforce_pre_auth_admission),  # noqa: B008
) -> AuthenticatedPrincipal:
    return await authenticate_bearer(authorization, credential_service)


async def enforce_rate_limit(
    principal: AuthenticatedPrincipal,
    *,
    operation: str,
    limit: int,
    window_seconds: int,
    fail_mode: FailMode,
    limiter: RateLimiterProtocol,
) -> None:
    """Authenticated, tenant+credential-scoped admission check -- called
    explicitly inside a route body immediately after require_permission(),
    the same style already used there (a plain call, not a second Depends
    layer). Most-restrictive-wins across the tenant and credential scopes
    (Foundation-010 discovery decision #3)."""
    rules = authenticated_rules(limit=limit, window_seconds=window_seconds)
    rules_and_keys = [
        (
            rule,
            build_scope_key(
                rule.scope,
                operation,
                tenant_id=principal.tenant_id,
                credential_id=str(principal.credential_id),
            ),
        )
        for rule in rules
    ]
    await evaluate_admission(
        rules_and_keys=rules_and_keys,
        limiter=limiter,
        fail_mode=fail_mode,
        metrics=RATE_LIMIT_METRICS,
    )
