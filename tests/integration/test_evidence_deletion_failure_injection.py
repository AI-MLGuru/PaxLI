"""Invariant-06 remediation Phase 5: real Postgres + MinIO failure
injection, bounded to exactly the three approved scenarios -- (1) MinIO
succeeds / DB fails, (2) DB succeeds / audit fails, (3) process
interruption then a fresh reconciler recovers. No worker, queue, or
distributed-transaction framework is introduced anywhere here: each
scenario drives the real SqlAlchemyEvidenceDeletionReconciler itself
through a genuine failure (not a hand-simulated replay of its internals,
which is what Phase 3's decisive test already covers) and proves recovery.

Skipped when either dependency isn't reachable, mirroring
tests/integration/test_evidence_deletion_service.py.
"""

import socket
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.enums import AuditEventType
from core.audit.service import AuditPersistenceError, AuditService
from core.deletion.enums import DeletionBasis
from core.evidence.enums import EvidenceType
from core.evidence.service import EvidenceService
from core.verification.service import VerificationSessionService
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.deletion.reconciliation import SqlAlchemyEvidenceDeletionReconciler
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


async def _create_session_row(session, tenant_id: str) -> str:
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
    key_provider = LocalAesGcmKeyProvider({"test-phase5-key": b"0" * 32})
    return EncryptedObjectStorage(MinioObjectStorage(settings), key_provider, "test-phase5-key")


async def _seed_requested_deletion(*, tenant_id: str, storage: EncryptedObjectStorage):
    """Creates and request_deletion()s one evidence item; returns
    (evidence, session_id) with the tombstone durably requested but not
    yet executed -- the common Phase-5 starting state."""
    async with session_factory() as session:
        session_id = await _create_session_row(session, tenant_id)
        session_repository = SqlAlchemyVerificationSessionRepository(session)
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(session_repository, session_ttl_minutes=60),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        evidence = await svc.add(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum=f"phase5-{uuid4()}",
            metadata={},
        )
        await svc.request_deletion(
            evidence_id=evidence.id,
            tenant_id=tenant_id,
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            basis_reference=None,
            authorized_by="admin-phase5",
        )
        await session.commit()
    return evidence, session_id


async def test_scenario_1_minio_succeeds_db_fails_then_retry_converges() -> None:
    """MinIO delete succeeds first (real, external, unrollback-able); the
    DB delete_content() step then fails inside the SAME real reconciler
    call. Proves: no false completion state, the already-gone storage
    object stays satisfied on retry, and the real reconciler converges
    exactly once with sensitive content gone from both stores."""
    tenant_id = f"tenant-phase5-s1-{uuid4()}"
    storage = _evidence_storage()
    evidence, session_id = await _seed_requested_deletion(tenant_id=tenant_id, storage=storage)

    reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    with patch.object(
        SqlAlchemyEvidenceRepository,
        "delete_content",
        side_effect=RuntimeError("simulated DB failure after storage delete succeeded"),
    ):
        with pytest.raises(RuntimeError):
            await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)

    # Intermediate state: storage genuinely gone, DB row still present (the
    # failure happened before delete_content could remove it), tombstone
    # still incomplete -- no false executed_at.
    with pytest.raises(Exception):  # noqa: B017 -- MinIO S3Error, not-found
        await storage.get(evidence.object_key)
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is not None
        tombstone = await repo.get_tombstone(evidence.id, tenant_id)
        assert tombstone is not None
        assert tombstone.executed_at is None

    # Real retry, unpatched: the already-gone object is treated as
    # satisfied, remaining DB + audit work completes.
    recovered = await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)
    assert recovered.executed_at is not None

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is None  # sensitive DB content gone

        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        deleted_events = await audit_service.list_for_tenant(
            tenant_id=tenant_id, event_type=AuditEventType.EVIDENCE_DELETED
        )
        assert len(deleted_events) == 1  # exactly one, no duplicate from the failed attempt

        # Constitutional boundary: deletion recovery must never touch
        # session lifecycle state or fabricate a verification outcome.
        session_repo = SqlAlchemyVerificationSessionRepository(session)
        verification_session = await session_repo.get(UUID(session_id), tenant_id)
        assert verification_session is not None
        assert verification_session.status.value == "CREATED"


async def test_scenario_2_db_succeeds_audit_fails_then_retry_converges() -> None:
    """The DB delete_content() step succeeds (staged, uncommitted) inside
    the SAME real reconciler call; the required audit write then fails.
    Proves the transaction boundary directly: DB delete, audit, and
    executed_at are one atomic unit sharing a single commit, so the system
    can never observably end up with content physically deleted,
    executed_at set, and the required completion audit absent -- Postgres
    itself rolls the DB delete back together with the failed audit, this
    is not merely an application-level promise."""
    tenant_id = f"tenant-phase5-s2-{uuid4()}"
    storage = _evidence_storage()
    evidence, session_id = await _seed_requested_deletion(tenant_id=tenant_id, storage=storage)

    reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    with patch.object(
        AuditService,
        "record",
        side_effect=AuditPersistenceError("simulated required-audit outage"),
    ):
        with pytest.raises(AuditPersistenceError):
            await reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)

    # Storage is genuinely gone (it happens before the DB transaction). The
    # staged DB delete was rolled back with the failed audit -- never
    # "deleted + executed_at set + no completion audit".
    with pytest.raises(Exception):  # noqa: B017 -- MinIO S3Error, not-found
        await storage.get(evidence.object_key)
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is not None
        tombstone = await repo.get_tombstone(evidence.id, tenant_id)
        assert tombstone is not None
        assert tombstone.executed_at is None

        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        deleted_events = await audit_service.list_for_tenant(
            tenant_id=tenant_id, event_type=AuditEventType.EVIDENCE_DELETED
        )
        assert len(deleted_events) == 0

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


async def test_scenario_3_process_interruption_then_fresh_reconciler_recovers() -> None:
    """Simulates a hard process interruption rather than a controlled
    exception: the storage delete completes, as if the process died
    immediately afterward, before any DB reconciliation transaction was
    even opened. Recovery is driven by a BRAND NEW reconciler instance --
    standing in for a freshly restarted process, since a real interruption
    leaves no continuation state in memory at all -- and must still
    converge to exactly one lifecycle audit pair and no fabricated
    verification outcome."""
    tenant_id = f"tenant-phase5-s3-{uuid4()}"
    storage = _evidence_storage()
    evidence, session_id = await _seed_requested_deletion(tenant_id=tenant_id, storage=storage)

    # The interruption: only the storage side completed before the process
    # died. No DB reconciliation transaction was ever opened.
    await storage.delete(evidence.object_key)

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is not None  # DB content untouched
        tombstone = await repo.get_tombstone(evidence.id, tenant_id)
        assert tombstone is not None
        assert tombstone.executed_at is None  # not falsely marked complete

    fresh_reconciler = SqlAlchemyEvidenceDeletionReconciler(session_factory, storage)
    recovered = await fresh_reconciler.reconcile(evidence_id=evidence.id, tenant_id=tenant_id)
    assert recovered.executed_at is not None

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        assert await repo.get(evidence.id, tenant_id) is None  # sensitive DB content gone

        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        events = await audit_service.list_for_tenant(tenant_id=tenant_id)
        deleted_events = [e for e in events if e.event_type == AuditEventType.EVIDENCE_DELETED]
        requested_events = [
            e for e in events if e.event_type == AuditEventType.EVIDENCE_DELETION_REQUESTED
        ]
        assert len(requested_events) == 1  # no duplicated lifecycle events
        assert len(deleted_events) == 1

        session_repo = SqlAlchemyVerificationSessionRepository(session)
        verification_session = await session_repo.get(UUID(session_id), tenant_id)
        assert verification_session is not None
        assert verification_session.status.value == "CREATED"  # no fabricated outcome

    with pytest.raises(Exception):  # noqa: B017 -- MinIO S3Error, not-found
        await storage.get(evidence.object_key)  # sensitive object content gone
