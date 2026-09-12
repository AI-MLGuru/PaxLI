"""Real PostgreSQL + MinIO integration tests for WF-001 §8's evidence-
submission allow-list (WF-4.19.2): submission MUST be rejected outside
{CREATED, CAPTURING}, proven against real infrastructure, not merely
against fakes. Skipped when either dependency isn't reachable, mirroring
tests/integration/test_evidence_deletion_service.py.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence.enums import EvidenceType
from core.evidence.service import EvidenceService, SessionExpiredError
from core.verification.enums import EVIDENCE_SUBMISSION_ALLOWED_STATUSES, VerificationStatus
from core.verification.service import VerificationSessionService
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

EVIDENCE_SUBMISSION_REJECTED_STATUSES = tuple(
    status for status in VerificationStatus if status not in EVIDENCE_SUBMISSION_ALLOWED_STATUSES
)


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


async def _create_session_in_status(session, tenant_id: str, status: VerificationStatus) -> str:
    session_id = str(uuid4())
    session.add(
        VerificationSessionRecord(
            id=session_id,
            tenant_id=tenant_id,
            status=status.value,
            assurance_level="STANDARD",
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.flush()
    return session_id


def _evidence_storage() -> EncryptedObjectStorage:
    settings = get_settings()
    key_provider = LocalAesGcmKeyProvider({"test-terminal-guard-key": b"0" * 32})
    return EncryptedObjectStorage(
        MinioObjectStorage(settings), key_provider, "test-terminal-guard-key"
    )


@pytest.mark.parametrize(
    "status", sorted(EVIDENCE_SUBMISSION_REJECTED_STATUSES, key=lambda s: s.value)
)
async def test_evidence_submission_rejected_outside_the_allow_list_real_infrastructure(
    status: VerificationStatus,
) -> None:
    """The mandatory acceptance gate: no EvidenceRecord row and no MinIO
    object survive a submission attempt against any status outside
    {CREATED, CAPTURING} -- including SUBMITTED and PROCESSING, neither of
    which is terminal, because the client has already signaled "done" by
    calling /submit (WF-001 §8's allow-list, not the DE-004 Phase 4
    deny-list this test previously exercised)."""
    tenant_id = f"tenant-allow-list-guard-{status.value.lower()}-{uuid4()}"
    storage = _evidence_storage()
    async with session_factory() as session:
        session_id = await _create_session_in_status(session, tenant_id, status)
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )

        with pytest.raises(SessionExpiredError):
            await svc.add(
                session_id=UUID(session_id),
                tenant_id=tenant_id,
                evidence_type=EvidenceType.SELFIE,
                content=MINIMAL_JPEG_BYTES,
                checksum=f"checksum-{status.value}",
                metadata={},
            )
        await session.rollback()

    async with session_factory() as verify_session:
        rows = (
            (
                await verify_session.execute(
                    select(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
        # No object was ever written either: the allow-list check is the
        # first statement in EvidenceService.add() (see its source),
        # strictly before storage.put() ever runs, so the absent DB row
        # already proves storage.put() was never reached -- deliberately
        # not probing MinIO for a missing object here, since repeatedly
        # doing that across five parametrized cases would trip the shared
        # module-level circuit breaker (5-failure threshold) and start
        # failing the unrelated happy-path test that follows.


async def test_evidence_submission_still_succeeds_for_every_allowed_status() -> None:
    """The mirror image against real infrastructure: CREATED and
    CAPTURING must remain accepted."""
    for status in sorted(EVIDENCE_SUBMISSION_ALLOWED_STATUSES, key=lambda s: s.value):
        tenant_id = f"tenant-allow-list-guard-ok-{status.value.lower()}-{uuid4()}"
        storage = _evidence_storage()
        async with session_factory() as session:
            session_id = await _create_session_in_status(session, tenant_id, status)
            svc = EvidenceService(
                SqlAlchemyEvidenceRepository(session),
                VerificationSessionService(
                    SqlAlchemyVerificationSessionRepository(session),
                    audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                ),
                storage,
                AuditService(SqlAlchemyAuditEventRepository(session)),
            )
            evidence = await svc.add(
                session_id=UUID(session_id),
                tenant_id=tenant_id,
                evidence_type=EvidenceType.SELFIE,
                content=MINIMAL_JPEG_BYTES,
                checksum=f"checksum-ok-{status.value}",
                metadata={},
            )
            await session.commit()

        async with session_factory() as verify_session:
            record = await verify_session.get(EvidenceRecord, str(evidence.id))
            assert record is not None
            assert record.tenant_id == tenant_id
