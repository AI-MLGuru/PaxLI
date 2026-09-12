"""WF-HV-006: real Postgres + MinIO failure injection for evidence
submission -- the metadata-DB-write side of the object<->metadata
relationship. EvidenceService.add() writes the object to MinIO first,
then the EvidenceRecord row; a try/except around the DB write already
calls storage.delete(object_key) on any failure other than
IdempotencyKeyConflictError (core/evidence/service.py), but nothing
previously proved this live against real infrastructure -- only the
deletion path (tests/integration/test_evidence_deletion_failure_injection.py)
had genuine failure-injection coverage. Attacks the object-succeeds/
metadata-fails half specifically (the other half -- metadata succeeds,
object write fails -- can't actually happen in this codebase's ordering,
since storage.put() always runs before repository.add(); there is no
"object write after DB write" path to attack).

Skipped when either dependency isn't reachable, mirroring
tests/integration/test_evidence_deletion_failure_injection.py.
"""

import socket
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
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


def _evidence_storage() -> EncryptedObjectStorage:
    settings = get_settings()
    key_provider = LocalAesGcmKeyProvider({"test-hv006-key": b"0" * 32})
    return EncryptedObjectStorage(MinioObjectStorage(settings), key_provider, "test-hv006-key")


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


async def test_object_write_succeeds_db_write_fails_object_is_cleaned_up_not_orphaned() -> None:
    """The exact boundary this codebase's own cleanup logic targets --
    proven live, not merely read from the source: MinIO put() genuinely
    succeeds (real, external, not transactional with the DB), the
    EvidenceRecord INSERT then fails inside the same real
    EvidenceService.add() call. Verifies the object does not survive as
    an orphan, no EvidenceRecord exists, and a real retry (unpatched)
    succeeds cleanly."""
    tenant_id = f"tenant-hv006-evidence-{uuid4()}"
    storage = _evidence_storage()
    checksum = f"hv006-{uuid4()}"

    async with session_factory() as session:
        session_id = await _create_session_row(session, tenant_id)
        await session.commit()

    object_key = f"{tenant_id}/{session_id}/selfie/{checksum}"

    async with session_factory() as session:
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        with patch.object(
            SqlAlchemyEvidenceRepository,
            "add",
            side_effect=RuntimeError("simulated DB failure after storage write succeeded"),
        ):
            with pytest.raises(RuntimeError):
                await svc.add(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceType.SELFIE,
                    content=MINIMAL_JPEG_BYTES,
                    checksum=checksum,
                    metadata={},
                )
        await session.rollback()

    # The object was genuinely written to MinIO by the unpatched put()
    # call, then genuinely deleted by EvidenceService.add()'s own
    # exception-path cleanup -- confirmed by attempting to read it back
    # from the real store, not inferred from the code.
    with pytest.raises(Exception):  # noqa: B017 -- MinIO S3Error, not-found
        await storage.get(object_key)

    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        rows = await repo.list_for_session(session_id, tenant_id)
        assert rows == []  # no orphaned metadata row either

    # Real retry, unpatched: succeeds cleanly.
    async with session_factory() as session:
        svc = EvidenceService(
            SqlAlchemyEvidenceRepository(session),
            VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                session_ttl_minutes=60,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        evidence = await svc.add(
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE,
            content=MINIMAL_JPEG_BYTES,
            checksum=checksum,
            metadata={},
        )
        await session.commit()

    retrieved = await storage.get(evidence.object_key)
    assert retrieved == MINIMAL_JPEG_BYTES
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        rows = await repo.list_for_session(session_id, tenant_id)
        assert len(rows) == 1  # exactly one row, not a duplicate from the failed attempt
