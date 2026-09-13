"""DP-002 Phase 1: real Postgres + MinIO integration tests for
SqlAlchemyDocumentProcessor -- the orchestration boundary between a
DOCUMENT capture and typed, lineage-bearing DOCUMENT_QUALITY/
DOCUMENT_CLASSIFICATION EvidenceResult rows.

Tested here rather than as pure unit tests against fakes: like
infrastructure.deletion.reconciliation's reconciler classes (the same
"needs its own independent sessions" shape, same testing convention
throughout this codebase), SqlAlchemyDocumentProcessor constructs real
SqlAlchemy repositories internally against session_factory -- there is
no fake-repository seam to unit-test against, and the two deterministic
capabilities (core.document.deterministic) are already covered by pure
unit tests (tests/unit/test_document_deterministic.py).

Skipped when Postgres and/or MinIO aren't reachable, mirroring
tests/integration/test_evidence_submission_failure_injection.py.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.document.capabilities import (
    CapabilityUnavailableError,
    DocumentClassifier,
    QualityAssessor,
)
from core.document.deterministic import (
    DeterministicDocumentClassifier,
    DeterministicQualityAssessor,
)
from core.document.types import DocumentClassification, QualityAssessment
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence_result.enums import DocumentType, EvidenceResultStatus
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.condition import EvidenceCondition
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.service import VerificationSessionService
from core.verification.workflow import VerificationWorkflowService
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.evidence_result import EvidenceResultRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.decision import SqlAlchemyDecisionRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.document.processor import SqlAlchemyDocumentProcessor
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


def _minio_reachable() -> bool:
    settings = get_settings()
    host, _, port = settings.storage_endpoint.partition(":")
    try:
        with socket.create_connection((host, int(port) if port else 9000), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(
        not (_postgres_reachable() and _minio_reachable()),
        reason="PostgreSQL and/or MinIO not reachable",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest.fixture(scope="module", autouse=True)
async def _dispose_shared_engine_pool_after_module():
    from infrastructure.database.session import engine

    yield
    await engine.dispose()


async def _create_session(session, tenant_id: str) -> str:
    session_id = str(uuid4())
    session.add(
        VerificationSessionRecord(
            id=session_id,
            tenant_id=tenant_id,
            status="CREATED",
            assurance_level="STANDARD",
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.flush()
    return session_id


def _storage(key_id: str) -> EncryptedObjectStorage:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return EncryptedObjectStorage(MinioObjectStorage(get_settings()), key_provider, key_id)


async def _upload_document(
    session, tenant_id: str, session_id: str, storage, content: bytes
) -> UUID:
    """Direct EvidenceRecord + real storage.put() -- mirrors
    EvidenceService.add()'s own object_key convention without pulling in
    the full router/session-lifecycle machinery these tests don't need."""
    evidence_id = uuid4()
    checksum = f"doc-{uuid4()}"
    object_key = f"{tenant_id}/{session_id}/document/{checksum}"
    await storage.put(object_key, content, "image/jpeg")
    session.add(
        EvidenceRecord(
            id=str(evidence_id),
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=EvidenceType.DOCUMENT.value,
            source=EvidenceSource.CLIENT.value,
            object_key=object_key,
            checksum=checksum,
            mime_type="image/jpeg",
            size_bytes=len(content),
            metadata_json={},
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return evidence_id


def _processor(
    key_id: str,
    storage,
    quality_assessor: QualityAssessor | None = None,
    document_classifier: DocumentClassifier | None = None,
) -> SqlAlchemyDocumentProcessor:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return SqlAlchemyDocumentProcessor(
        session_factory,
        key_provider,
        key_id,
        storage,
        quality_assessor or DeterministicQualityAssessor(),
        document_classifier or DeterministicDocumentClassifier(),
    )


async def _effective_result(session, session_id: str, tenant_id: str, evidence_type: str):
    result = await session.execute(
        select(EvidenceResultRecord).where(
            EvidenceResultRecord.session_id == session_id,
            EvidenceResultRecord.tenant_id == tenant_id,
            EvidenceResultRecord.evidence_type == evidence_type,
            EvidenceResultRecord.is_effective.is_(True),
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Counting/failing capability doubles -- real classes, not mocks, matching
# this project's established failure-injection convention.
# ---------------------------------------------------------------------------


class _CountingQualityAssessor(QualityAssessor):
    def __init__(self, delegate: QualityAssessor) -> None:
        self.calls = 0
        self._delegate = delegate

    async def assess(self, image: bytes) -> QualityAssessment:
        self.calls += 1
        return await self._delegate.assess(image)


class _CountingDocumentClassifier(DocumentClassifier):
    def __init__(self, delegate: DocumentClassifier) -> None:
        self.calls = 0
        self._delegate = delegate

    async def classify(self, image: bytes) -> DocumentClassification:
        self.calls += 1
        return await self._delegate.classify(image)


class _UnavailableQualityAssessor(QualityAssessor):
    async def assess(self, image: bytes) -> QualityAssessment:
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


class _BuggyQualityAssessor(QualityAssessor):
    """Simulates a genuine programming defect -- NOT a known, self-
    diagnosed failure. DP-002's exception-taxonomy amendment requires
    this to propagate out of DocumentProcessor uncaught, never silently
    normalized into an ordinary UNAVAILABLE result."""

    async def assess(self, image: bytes) -> QualityAssessment:
        raise AttributeError("simulated programming defect, not a known capability failure")


async def test_full_round_trip_produces_correct_quality_and_classification() -> None:
    tenant_id = f"tenant-docproc-happy-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value
        assert quality.source_reference == str(capture_id)
        assert quality.result_json == {"quality_score": 1.0}

        assert classification is not None
        assert classification.status == EvidenceResultStatus.PASS.value
        assert classification.source_reference == str(capture_id)
        assert classification.result_json == {"document_type": DocumentType.STANDARD_NIN_SLIP.value}


async def test_unrecognized_document_fails_classification_but_not_quality() -> None:
    """Partial-stage independence (DP-001 Decision 2/REL-10.15): an
    unrecognized document must not affect the independently-computed
    quality result."""
    tenant_id = f"tenant-docproc-unsupported-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"not a recognized document at all",
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value  # unaffected

        assert classification is not None
        assert classification.status == EvidenceResultStatus.FAIL.value
        assert classification.reason_codes_json == ["DOCUMENT_UNSUPPORTED"]
        assert classification.result_json is None


async def test_zero_captures_is_a_noop() -> None:
    tenant_id = f"tenant-docproc-none-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        assert await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY") is None
        assert (
            await _effective_result(session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION")
            is None
        )


async def test_ambiguous_captures_produce_inconclusive_without_invoking_any_capability() -> None:
    """DP-002 reconciliation amendment: more than one eligible DOCUMENT
    capture is an explicit precondition failure, checked BEFORE any
    capability runs -- never an implicit selection rule."""
    tenant_id = f"tenant-docproc-ambiguous-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES + b"0" * 2000 + b"one"
        )
        await _upload_document(
            session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES + b"0" * 2000 + b"two"
        )
        await session.commit()

    quality_assessor = _CountingQualityAssessor(DeterministicQualityAssessor())
    document_classifier = _CountingDocumentClassifier(DeterministicDocumentClassifier())
    processor = _processor(key_id, storage, quality_assessor, document_classifier)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert quality_assessor.calls == 0  # precondition short-circuits before any capability runs
    assert document_classifier.calls == 0

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        for result in (quality, classification):
            assert result is not None
            assert result.status == EvidenceResultStatus.INCONCLUSIVE.value
            assert result.reason_codes_json == ["AMBIGUOUS_DOCUMENT_CAPTURE"]
            assert result.source_reference is None  # no single capture to attribute to


async def test_concurrent_process_calls_converge_on_one_effective_result_per_type() -> None:
    """HV-010: two concurrent process() calls for the same session (the
    real-world shape of a client double-submitting, or WF-006's GET-
    triggered PROCESSING recovery racing a still-in-flight /submit) must
    not both reach create() for the same (session_id, evidence_type) --
    the partial unique index on is_effective is the final backstop, but a
    raw IntegrityError surfacing out of DocumentProcessor.process() would
    still be a real defect this test rules out directly, mirroring
    test_submit_api_wiring.py's own concurrent-convergence proof one layer
    up."""
    tenant_id = f"tenant-docproc-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    processor_a = _processor(key_id, storage)
    processor_b = _processor(key_id, storage)

    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    async with session_factory() as session:
        for evidence_type in ("DOCUMENT_QUALITY", "DOCUMENT_CLASSIFICATION"):
            effective_rows = await session.execute(
                select(EvidenceResultRecord).where(
                    EvidenceResultRecord.session_id == session_id,
                    EvidenceResultRecord.evidence_type == evidence_type,
                    EvidenceResultRecord.is_effective.is_(True),
                )
            )
            rows = effective_rows.scalars().all()
            assert len(rows) == 1, (
                f"{evidence_type}: expected exactly one effective row, got {len(rows)}"
            )
            assert rows[0].status == EvidenceResultStatus.PASS.value
            assert rows[0].source_reference == str(capture_id)


async def test_retry_does_not_recompute_an_already_reusable_result() -> None:
    tenant_id = f"tenant-docproc-convergence-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE",
        )
        await session.commit()

    quality_assessor = _CountingQualityAssessor(DeterministicQualityAssessor())
    document_classifier = _CountingDocumentClassifier(DeterministicDocumentClassifier())
    processor = _processor(key_id, storage, quality_assessor, document_classifier)

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert quality_assessor.calls == 1
    assert document_classifier.calls == 1

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert quality_assessor.calls == 1  # NOT recomputed -- PASS is terminal/reusable
    assert document_classifier.calls == 1


async def test_capability_unavailable_error_produces_unavailable_result_and_is_retryable() -> None:
    tenant_id = f"tenant-docproc-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    failing_processor = _processor(key_id, storage, quality_assessor=_UnavailableQualityAssessor())
    await failing_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.UNAVAILABLE.value
        assert quality.reason_codes_json == ["MODEL_UNAVAILABLE"]
        first_attempt_id = quality.id

    # A real retry (a working capability this time) MUST supersede the
    # prior UNAVAILABLE attempt, not create a second effective result.
    working_processor = _processor(key_id, storage)
    await working_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value
        assert quality.id != first_attempt_id
        assert quality.supersedes_id == first_attempt_id

        # Exactly one effective DOCUMENT_QUALITY row -- the partial unique
        # index's own guarantee, confirmed directly.
        result = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id,
                EvidenceResultRecord.evidence_type == "DOCUMENT_QUALITY",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        assert len(result.scalars().all()) == 1


async def test_unexpected_capability_exception_propagates_uncaught() -> None:
    """DP-002 reconciliation amendment B: only CapabilityUnavailableError
    is caught. A bug in a capability implementation must remain
    observable, never silently normalized into an ordinary-looking
    UNAVAILABLE result -- this is the test that would have caught the
    original 'catch bare Exception' draft before it shipped."""
    tenant_id = f"tenant-docproc-defect-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    processor = _processor(key_id, storage, quality_assessor=_BuggyQualityAssessor())

    # asyncio.gather (no return_exceptions=True) re-raises the failing
    # task's own exception type directly, not wrapped -- confirmed here
    # rather than assumed, since this is the one assertion this whole
    # amendment exists to prove.
    with pytest.raises(AttributeError, match="simulated programming defect"):
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        # No DOCUMENT_QUALITY row was fabricated to paper over the defect.
        assert await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY") is None


async def test_document_unsupported_lets_policy_not_document_processor_decide_outcome() -> None:
    """DP-001 Decision 5: DOCUMENT_UNSUPPORTED is an evidence-level
    outcome, never a session-level verdict DocumentProcessor itself
    determines. Two policies, identical unrecognized-document evidence,
    two different final outcomes -- proving the separation is real, not
    just documented. Drives the full real /submit path (workflow ->
    DocumentProcessor -> DecisionOrchestrator -> persisted decision),
    matching test_decision_orchestration.py's full-pipeline pattern one
    layer up."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})

    async def _decide(rule_outcome: DecisionOutcome, reason_code: str) -> DecisionOutcome:
        tenant_id = f"tenant-docproc-separation-{uuid4()}"
        async with session_factory() as session:
            policy_service = PolicyService(
                SqlAlchemyVerificationPolicyRepository(session),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                EvidenceResultSchemaCatalog(),
            )
            await policy_service.create_and_activate(
                tenant_id=tenant_id,
                policy_id="policy-docproc-separation",
                assurance_level=AssuranceLevel.STANDARD,
                created_by="admin",
                evidence_requirements=(
                    EvidenceRequirement(
                        evidence_type="DOCUMENT_CLASSIFICATION",
                        level=EvidenceRequirementLevel.REQUIRED,
                    ),
                ),
                rules=(
                    Rule(
                        id="r1",
                        condition=EvidenceCondition(
                            evidence_type="DOCUMENT_CLASSIFICATION",
                            field="status",
                            operator="==",
                            expected_value="FAIL",
                        ),
                        outcome=rule_outcome,
                        priority=10,
                        reason_code=reason_code,
                    ),
                ),
            )
            session_service = VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                policy_service=policy_service,
                session_ttl_minutes=30,
            )
            created_session = await session_service.create(
                tenant_id=tenant_id,
                external_reference=None,
                assurance_level=AssuranceLevel.STANDARD,
            )
            await session.commit()

        async with session_factory() as session:
            await _upload_document(
                session, tenant_id, str(created_session.id), storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + b"not a recognized document at all",
            )
            await session.commit()

        async with session_factory() as session:
            policy_service = PolicyService(
                SqlAlchemyVerificationPolicyRepository(session),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                EvidenceResultSchemaCatalog(),
            )
            session_service = VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                policy_service=policy_service,
                session_ttl_minutes=30,
            )
            evidence_result_service = EvidenceResultService(
                SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                SqlAlchemyEvidenceRepository(session),
            )
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            persistence_service = DecisionPersistenceService(
                SqlAlchemyDecisionRepository(session), audit_service
            )
            orchestrator = DecisionOrchestrator(
                session_service, policy_service, evidence_result_service,
                persistence_service, audit_service,
            )
            document_processor = SqlAlchemyDocumentProcessor(
                session_factory, key_provider, key_id, storage,
                DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
            )
            workflow = VerificationWorkflowService(
                session_service, orchestrator, audit_service, document_processor
            )
            _session, decision = await workflow.submit(
                session_id=created_session.id, tenant_id=tenant_id
            )
            await session.commit()
        return decision.outcome

    rejected = await _decide(DecisionOutcome.REJECTED, "POLICY:DOCUMENT_REJECTED")
    review_required = await _decide(DecisionOutcome.REVIEW_REQUIRED, "POLICY:DOCUMENT_REVIEW")

    assert rejected is DecisionOutcome.REJECTED
    assert review_required is DecisionOutcome.REVIEW_REQUIRED


async def test_concurrent_submit_with_a_real_document_converges_on_one_decision() -> None:
    """HV-010 category 5: the SAME race
    test_submit_api_wiring.py's test_workflow_service_di_wiring_concurrent_
    submit_converges already proves at the workflow-DI level, but that
    test uploads no evidence at all, so DocumentProcessor always took its
    zero-captures no-op path there -- it never actually exercised
    DocumentProcessor under concurrency. workflow.py's submit() has no CAS
    gate immediately around document_processor.process() itself: the CAS
    transition into PROCESSING only gates WHICH caller performs that one
    hop, but both a winner that just transitioned in and a caller that
    independently finds the session already sitting in PROCESSING land in
    the same branch and both call document_processor.process() -- so this
    race is genuinely reachable through the real submit() entrypoint, not
    a scenario invented only at the DocumentProcessor layer. With a real
    DOCUMENT evidence capture present, drives two full concurrent
    submit() calls through the DI-equivalent stack and confirms they
    converge on one decision AND exactly one effective row per document
    evidence-result type, closing the loop from the isolated
    DocumentProcessor-level proof
    (test_concurrent_process_calls_converge_on_one_effective_result_per_type)
    up through the real public entrypoint."""
    tenant_id = f"tenant-docproc-submit-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-docproc-submit-race",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            default_outcome=DecisionOutcome.INCONCLUSIVE,
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    async with session_factory() as session:
        capture_id = await _upload_document(
            session, tenant_id, str(created_session.id), storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    def _build_workflow(session: AsyncSession) -> VerificationWorkflowService:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        persistence_service = DecisionPersistenceService(
            SqlAlchemyDecisionRepository(session), audit_service
        )
        orchestrator = DecisionOrchestrator(
            session_service, policy_service, evidence_result_service,
            persistence_service, audit_service,
        )
        document_processor = SqlAlchemyDocumentProcessor(
            session_factory, key_provider, key_id, storage,
            DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
        )
        return VerificationWorkflowService(
            session_service, orchestrator, audit_service, document_processor
        )

    async def _submit_attempt() -> UUID:
        async with session_factory() as session:
            workflow = _build_workflow(session)
            _session, decision = await workflow.submit(
                session_id=created_session.id, tenant_id=tenant_id
            )
            await session.commit()
            return decision.decision_id

    decision_ids = await asyncio.gather(_submit_attempt(), _submit_attempt())
    assert decision_ids[0] == decision_ids[1]

    async with session_factory() as session:
        for evidence_type in ("DOCUMENT_QUALITY", "DOCUMENT_CLASSIFICATION"):
            effective_rows = (
                await session.execute(
                    select(EvidenceResultRecord).where(
                        EvidenceResultRecord.session_id == str(created_session.id),
                        EvidenceResultRecord.evidence_type == evidence_type,
                        EvidenceResultRecord.is_effective.is_(True),
                    )
                )
            ).scalars().all()
            assert len(effective_rows) == 1, (
                f"{evidence_type}: expected exactly one effective row, got {len(effective_rows)}"
            )
            assert effective_rows[0].source_reference == str(capture_id)
