"""Real PostgreSQL + MinIO integration tests for Invariant-06 remediation
Phase 3 (deletion services): the request/reconciliation transaction pair,
end to end, against real infrastructure. Skipped when either dependency
isn't reachable, mirroring tests/integration/test_dependency_reliability.py.

The decisive test here (`test_reconciliation_recovers_after_a_required_
audit_failure`) proves the exact crash-tolerance property Phase 3 was
approved on: a required-audit failure aborts the reconciliation transaction
(so the DB content delete is rolled back with it), but the prior, already-
committed storage delete is NOT undone -- and a retry of the real
reconciler converges correctly regardless, never re-emitting a duplicate
EVIDENCE_DELETED audit event and never setting executed_at until the
defined deletion scope has actually been satisfied.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditPersistenceError, AuditService
from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import DeletionBlockedByDependentsError, TombstoneNotFoundError
from core.evidence.enums import EvidenceType
from core.evidence.service import EvidenceService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.service import EvidenceResultService
from core.verification.service import VerificationSessionService
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.deletion.reconciliation import (
    SqlAlchemyEvidenceDeletionReconciler,
    SqlAlchemyEvidenceResultDeletionReconciler,
)
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


def _evidence_storage() -> EncryptedObjectStorage:
    settings = get_settings()
    key_provider = LocalAesGcmKeyProvider({"test-deletion-svc-key": b"0" * 32})
    return EncryptedObjectStorage(
        MinioObjectStorage(settings), key_provider, "test-deletion-svc-key"
    )


class FailingAuditEventRepository:
    """Same shape as test_evidence_result_persistence.py's fake: simulates
    a required audit write that fails, without touching real Postgres."""

    async def add(self, event, dedupe_key=None):
        raise RuntimeError("simulated audit database outage")

    async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
        return None

    async def list_for_session(self, session_id, tenant_id):
        return []


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


async def test_full_lifecycle_deletes_storage_and_db_and_audits_both_phases() -> None:
    tenant_id = f"tenant-del-lifecycle-{uuid4()}"
    storage = _evidence_storage()
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        evidence = await svc.add(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="canary-checksum",
            metadata={},
        )
        await session.commit()

    async with session_factory() as session:
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        await svc.request_deletion(
            evidence_id=evidence.id,
            tenant_id=tenant_id,
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )
        await session.commit()

    reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    tombstone = await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)
    assert tombstone.executed_at is not None

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is None

        with pytest.raises(Exception):  # noqa: B017 -- MinIO S3Error, not-found
            await storage.get(evidence.object_key)

        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        events = await audit_service.list_for_tenant(tenant_id=tenant_id)
        event_types = {e.event_type for e in events}
        assert AuditEventType.EVIDENCE_DELETION_REQUESTED in event_types
        assert AuditEventType.EVIDENCE_DELETED in event_types


async def test_reconcile_deletion_is_idempotent_when_already_executed() -> None:
    tenant_id = f"tenant-del-idempotent-{uuid4()}"
    storage = _evidence_storage()
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        evidence = await svc.add(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="canary-checksum-2",
            metadata={},
        )
        await svc.request_deletion(
            evidence_id=evidence.id,
            tenant_id=tenant_id,
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )
        await session.commit()

    reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    first = await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)
    second = await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)
    assert first.executed_at == second.executed_at

    async with session_factory() as session:
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        events = await audit_service.list_for_tenant(
            tenant_id=tenant_id, event_type=AuditEventType.EVIDENCE_DELETED
        )
        assert len(events) == 1


async def test_reconcile_deletion_raises_without_prior_request() -> None:
    storage = _evidence_storage()
    reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    with pytest.raises(TombstoneNotFoundError):
        await reconciler.reconcile(evidence_id=uuid4(), tenant_id=f"tenant-{uuid4()}")


async def test_request_deletion_is_blocked_by_a_dependent_evidence_result() -> None:
    """Phase 6 finding: evidence_results.source_reference -> evidence.id is
    a foreign key with no ON DELETE behavior. Letting a request through
    when a dependent exists would delete the MinIO object, then hit a
    ForeignKeyViolation on the DB delete that no retry could ever resolve.
    request_deletion() must reject this before anything is touched."""
    tenant_id = f"tenant-del-blocked-{uuid4()}"
    storage = _evidence_storage()
    key_provider = LocalAesGcmKeyProvider({"test-deletion-svc-key": b"0" * 32})
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        evidence_svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        evidence = await evidence_svc.add(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum=f"canary-blocked-{uuid4()}",
            metadata={},
        )
        result_svc = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-svc-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        await result_svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
            source_reference=evidence.id,
        )
        await session.commit()

    async with session_factory() as session:
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        evidence_svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        with pytest.raises(DeletionBlockedByDependentsError):
            await evidence_svc.request_deletion(
                evidence_id=evidence.id,
                tenant_id=tenant_id,
                deletion_basis=DeletionBasis.TENANT_REQUEST,
                basis_reference=None,
                authorized_by="admin-1",
            )

    # Nothing was touched: no tombstone, storage object still present.
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get_tombstone(evidence.id, tenant_id) is None
    content = await storage.get(evidence.object_key)
    assert content == MINIMAL_JPEG_BYTES


async def test_evidence_result_request_deletion_is_blocked_by_dependent_supersession() -> None:
    """Same root cause, self-referencing: evidence_results.supersedes_id ->
    evidence_results.id."""
    tenant_id = f"tenant-result-del-blocked-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-deletion-result-key": b"0" * 32})

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        original = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
            status=EvidenceResultStatus.INCONCLUSIVE,
            producer="p",
            producer_version="1",
        )
        await svc.supersede(
            evidence_result_id=original.id,
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
        )
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        with pytest.raises(DeletionBlockedByDependentsError):
            await svc.request_deletion(
                evidence_result_id=original.id,
                tenant_id=tenant_id,
                deletion_basis=DeletionBasis.TENANT_REQUEST,
                basis_reference=None,
                authorized_by="admin-1",
            )

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-result-key")
        assert await repo.get_tombstone(original.id, tenant_id) is None
        assert await repo.get(original.id, tenant_id) is not None


async def test_reconciliation_recovers_after_a_required_audit_failure() -> None:
    """The decisive Phase-3 crash-tolerance proof: storage DELETE already
    committed (external, real MinIO), DB DELETE + audit rolled back
    together when the audit write fails -- then a real retry converges."""
    tenant_id = f"tenant-del-crash-{uuid4()}"
    storage = _evidence_storage()
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        evidence = await svc.add(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum="canary-checksum-crash",
            metadata={},
        )
        await svc.request_deletion(
            evidence_id=evidence.id,
            tenant_id=tenant_id,
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )
        await session.commit()

    # -- Simulated crashed reconciliation attempt: storage delete for real,
    # DB delete within an uncommitted transaction, then a required-audit
    # failure aborts before commit.
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        live = await repo.get(evidence.id, tenant_id)
        assert live is not None
        await storage.delete(live.object_key)  # real MinIO delete -- survives the rollback below
        await repo.delete_content(evidence.id, tenant_id)

        failing_audit_service = AuditService(FailingAuditEventRepository())
        with pytest.raises(AuditPersistenceError):
            await failing_audit_service.record(
                tenant_id=tenant_id,
                session_id=UUID(session_id),
                event_type=AuditEventType.EVIDENCE_DELETED,
                component="evidence",
                action="reconcile_deletion",
                status=AuditStatus.SUCCESS,
                actor_type=AuditActorType.SYSTEM,
                actor_id="test-simulated-crash",
                metadata={"evidence_id": str(evidence.id)},
                dedupe_key=f"evidence-deleted:{evidence.id}",
                durability=AuditDurability.REQUIRED,
            )
        await session.rollback()

    # Verify the intermediate, "crashed" state: DB delete was rolled back
    # (the row reappears -- it was never durably committed), the tombstone
    # is still incomplete, but the storage object is genuinely gone.
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is not None
        tombstone = await repo.get_tombstone(evidence.id, tenant_id)
        assert tombstone is not None
        assert tombstone.executed_at is None

    with pytest.raises(Exception):  # noqa: B017 -- MinIO S3Error, not-found
        await storage.get(live.object_key)

    # Retry with the real reconciler: must converge correctly, exactly once.
    reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    recovered = await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)
    assert recovered.executed_at is not None

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is None

        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        deleted_events = await audit_service.list_for_tenant(
            tenant_id=tenant_id, event_type=AuditEventType.EVIDENCE_DELETED
        )
        assert len(deleted_events) == 1


# ---------------------------------------------------------------------------
# Evidence results
# ---------------------------------------------------------------------------


async def test_evidence_result_full_lifecycle_deletes_db_and_audits_both_phases() -> None:
    tenant_id = f"tenant-result-del-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-deletion-result-key": b"0" * 32})

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        result = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
        )
        await svc.request_deletion(
            evidence_result_id=result.id,
            tenant_id=tenant_id,
            deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )
        await session.commit()

    reconciler = SqlAlchemyEvidenceResultDeletionReconciler(
        session_factory, key_provider, "test-deletion-result-key"
    )
    tombstone = await reconciler.reconcile(evidence_result_id=result.id, tenant_id=tenant_id)
    assert tombstone.executed_at is not None

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-result-key")
        assert await repo.get(result.id, tenant_id) is None

        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        events = await audit_service.list_for_tenant(tenant_id=tenant_id)
        event_types = {e.event_type for e in events}
        assert AuditEventType.EVIDENCE_RESULT_DELETION_REQUESTED in event_types
        assert AuditEventType.EVIDENCE_RESULT_DELETED in event_types


async def test_evidence_result_reconcile_deletion_is_idempotent() -> None:
    tenant_id = f"tenant-result-del-idem-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-deletion-result-key": b"0" * 32})

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        result = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
        )
        await svc.request_deletion(
            evidence_result_id=result.id,
            tenant_id=tenant_id,
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-1",
        )
        await session.commit()

    reconciler = SqlAlchemyEvidenceResultDeletionReconciler(
        session_factory, key_provider, "test-deletion-result-key"
    )
    first = await reconciler.reconcile(evidence_result_id=result.id, tenant_id=tenant_id)
    second = await reconciler.reconcile(evidence_result_id=result.id, tenant_id=tenant_id)
    assert first.executed_at == second.executed_at

    async with session_factory() as session:
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        events = await audit_service.list_for_tenant(
            tenant_id=tenant_id, event_type=AuditEventType.EVIDENCE_RESULT_DELETED
        )
        assert len(events) == 1


async def test_evidence_result_reconcile_deletion_raises_without_prior_request() -> None:
    key_provider = LocalAesGcmKeyProvider({"test-deletion-result-key": b"0" * 32})
    reconciler = SqlAlchemyEvidenceResultDeletionReconciler(
        session_factory, key_provider, "test-deletion-result-key"
    )
    with pytest.raises(TombstoneNotFoundError):
        await reconciler.reconcile(evidence_result_id=uuid4(), tenant_id=f"tenant-{uuid4()}")
