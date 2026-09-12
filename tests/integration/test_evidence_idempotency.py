"""Real PostgreSQL + MinIO integration tests for WF-001 §10's evidence-
submission idempotency fingerprint, under a genuine concurrent race -- not
merely against fakes. Same barrier-synchronized methodology as
tests/integration/test_verification_session_idempotency.py: an
asyncio.Event forces the second attempt's INSERT to genuinely block on the
first's still-open, uncommitted unique-index entry. Skipped when either
dependency isn't reachable, mirroring
tests/integration/test_evidence_service_terminal_state.py.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence.enums import EvidenceType
from core.evidence.exceptions import IdempotencyKeyReusedError
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


async def _create_session(tenant_id: str) -> UUID:
    session_id = uuid4()
    async with session_factory() as session:
        session.add(
            VerificationSessionRecord(
                id=str(session_id),
                tenant_id=tenant_id,
                status="CREATED",
                assurance_level="STANDARD",
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    return session_id


def _evidence_storage() -> EncryptedObjectStorage:
    settings = get_settings()
    key_provider = LocalAesGcmKeyProvider({"test-idempotency-key": b"0" * 32})
    return EncryptedObjectStorage(
        MinioObjectStorage(settings), key_provider, "test-idempotency-key"
    )


def _evidence_service(session, storage) -> EvidenceService:
    return EvidenceService(
        SqlAlchemyEvidenceRepository(session),
        VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
        ),
        storage,
        AuditService(SqlAlchemyAuditEventRepository(session)),
    )


async def test_concurrent_submission_same_key_matching_fields_converges() -> None:
    """WF-001 §10: two requests racing to submit evidence under the same
    Idempotency-Key with an equivalent checksum. The database's unique
    index on (tenant_id, session_id, idempotency_key) resolves the race,
    never an application-level check-then-insert -- both requests must
    converge on exactly one durable row."""
    tenant_id = f"tenant-evidence-idem-match-{uuid4()}"
    session_id = await _create_session(tenant_id)
    storage = _evidence_storage()
    first_started = asyncio.Event()

    async def _submit_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> UUID:
        async with session_factory() as db_session:
            service = _evidence_service(db_session, storage)
            if wait_for_signal:
                await first_started.wait()
            try:
                result = await service.add(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceType.SELFIE,
                    content=MINIMAL_JPEG_BYTES,
                    checksum="checksum-race-match",
                    metadata={},
                    idempotency_key="req-race-match",
                )
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return result.id

    ids = await asyncio.gather(
        _submit_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _submit_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    assert ids[0] == ids[1]

    async with session_factory() as verify_session:
        rows = (
            await SqlAlchemyEvidenceRepository(verify_session).list_for_session(
                session_id, tenant_id
            )
        )
        assert len(rows) == 1  # exactly one row ever persisted, despite two attempts


async def test_concurrent_submission_same_key_mismatched_fields_one_rejected() -> None:
    """The other half of the same race: the two concurrent submissions
    disagree on WHAT was being submitted (different file content).
    Whichever attempt's INSERT loses the database's unique-index race must
    recover by re-fetching the winner and comparing fingerprints --
    discovering the mismatch and raising IdempotencyKeyReusedError, never
    silently resolving to the winner's evidence as if it were its own."""
    tenant_id = f"tenant-evidence-idem-mismatch-{uuid4()}"
    session_id = await _create_session(tenant_id)
    storage = _evidence_storage()
    first_started = asyncio.Event()

    async def _submit_attempt(
        *, checksum: str, wait_for_signal: bool, delay_before_commit: float
    ) -> str:
        async with session_factory() as db_session:
            service = _evidence_service(db_session, storage)
            if wait_for_signal:
                await first_started.wait()
            try:
                try:
                    await service.add(
                        session_id=session_id,
                        tenant_id=tenant_id,
                        evidence_type=EvidenceType.SELFIE,
                        content=MINIMAL_JPEG_BYTES,
                        checksum=checksum,
                        metadata={},
                        idempotency_key="req-race-mismatch",
                    )
                except IdempotencyKeyReusedError:
                    await db_session.rollback()
                    return "rejected"
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return "won"

    results = await asyncio.gather(
        _submit_attempt(
            checksum="checksum-A", wait_for_signal=False, delay_before_commit=0.5
        ),
        _submit_attempt(
            checksum="checksum-B", wait_for_signal=True, delay_before_commit=0.0
        ),
    )

    assert sorted(results) == ["rejected", "won"]

    async with session_factory() as verify_session:
        rows = await SqlAlchemyEvidenceRepository(verify_session).list_for_session(
            session_id, tenant_id
        )
        assert len(rows) == 1  # only the winner's row was ever persisted
        assert rows[0].checksum == "checksum-A"  # the attempt that committed first
