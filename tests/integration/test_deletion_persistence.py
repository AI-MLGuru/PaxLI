"""Real PostgreSQL integration tests for Invariant-06 remediation Phase 2
(deletion tombstone persistence). Skipped when Postgres isn't reachable,
mirroring tests/integration/test_evidence_result_persistence.py's pattern.

Scope: repository-level primitives only (add_tombstone, get_tombstone,
mark_tombstone_executed, delete_content, list_expired). The two-transaction
request/reconciliation orchestration itself is a Phase-3 service concern
and is not exercised here.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from apps.api.paxli_api.config import get_settings
from core.deletion.enums import DeletionBasis
from core.deletion.exceptions import DeletionAlreadyRequestedError, TombstoneNotFoundError
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence.models import Evidence, EvidenceTombstone
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult, EvidenceResultTombstone
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable"),
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


async def _create_evidence(
    session, tenant_id: str, session_id: str, *, retention_until: datetime | None = None
) -> Evidence:
    repo = SqlAlchemyEvidenceRepository(session)
    evidence = Evidence(
        session_id=UUID(session_id),
        tenant_id=tenant_id,
        evidence_type=EvidenceType.SELFIE,
        source=EvidenceSource.CLIENT,
        object_key=f"tenant/{tenant_id}/{uuid4()}",
        checksum="a" * 64,
        mime_type="image/jpeg",
        size_bytes=1024,
        retention_until=retention_until,
    )
    return await repo.add(evidence)


async def _create_evidence_result(
    session, tenant_id: str, session_id: str, *, retention_until: datetime | None = None
) -> EvidenceResult:
    key_provider = LocalAesGcmKeyProvider({"test-deletion-key": b"0" * 32})
    repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-deletion-key")
    result = EvidenceResult(
        tenant_id=tenant_id,
        session_id=UUID(session_id),
        evidence_type=EvidenceResultType.FACE_MATCH,
        status=EvidenceResultStatus.PASS,
        producer="p",
        producer_version="1",
        integrity_reference="deadbeef",
        retention_until=retention_until,
    )
    return await repo.add(result)


# ---------------------------------------------------------------------------
# Evidence tombstones
# ---------------------------------------------------------------------------


async def test_add_and_get_tombstone_round_trips() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-tombstone-a")
        evidence = await _create_evidence(session, "tenant-tombstone-a", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        tombstone = EvidenceTombstone(
            evidence_id=evidence.id,
            session_id=UUID(session_id),
            tenant_id="tenant-tombstone-a",
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            authorized_by="admin-1",
            evidence_integrity_reference=evidence.checksum,
        )
        await repo.add_tombstone(tombstone)
        await session.commit()

        fetched = await repo.get_tombstone(evidence.id, "tenant-tombstone-a")
        assert fetched is not None
        assert fetched.requested_at is not None
        assert fetched.executed_at is None


async def test_duplicate_tombstone_creation_is_rejected_by_primary_key() -> None:
    """Proves the invariant the user explicitly required: duplicate
    tombstone creation cannot occur under concurrent deletion requests.
    The primary key on evidence_id, not application-level locking, is what
    backs this."""
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-tombstone-dup")
        evidence = await _create_evidence(session, "tenant-tombstone-dup", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        first = EvidenceTombstone(
            evidence_id=evidence.id,
            session_id=UUID(session_id),
            tenant_id="tenant-tombstone-dup",
            deletion_basis=DeletionBasis.TENANT_REQUEST,
            authorized_by="admin-1",
            evidence_integrity_reference=evidence.checksum,
        )
        await repo.add_tombstone(first)
        await session.commit()

        second = EvidenceTombstone(
            evidence_id=evidence.id,
            session_id=UUID(session_id),
            tenant_id="tenant-tombstone-dup",
            deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,
            authorized_by="admin-2",
            evidence_integrity_reference=evidence.checksum,
        )
        with pytest.raises(DeletionAlreadyRequestedError):
            await repo.add_tombstone(second)
        await session.rollback()


async def test_cross_tenant_get_tombstone_returns_none() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-tombstone-iso-a")
        evidence = await _create_evidence(session, "tenant-tombstone-iso-a", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        await repo.add_tombstone(
            EvidenceTombstone(
                evidence_id=evidence.id,
                session_id=UUID(session_id),
                tenant_id="tenant-tombstone-iso-a",
                deletion_basis=DeletionBasis.TENANT_REQUEST,
                authorized_by="admin-1",
                evidence_integrity_reference=evidence.checksum,
            )
        )
        await session.commit()

        assert await repo.get_tombstone(evidence.id, "tenant-tombstone-iso-b") is None
        assert await repo.get_tombstone(evidence.id, "tenant-tombstone-iso-a") is not None


async def test_mark_tombstone_executed_sets_executed_at() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-tombstone-exec")
        evidence = await _create_evidence(session, "tenant-tombstone-exec", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        await repo.add_tombstone(
            EvidenceTombstone(
                evidence_id=evidence.id,
                session_id=UUID(session_id),
                tenant_id="tenant-tombstone-exec",
                deletion_basis=DeletionBasis.TENANT_REQUEST,
                authorized_by="admin-1",
                evidence_integrity_reference=evidence.checksum,
            )
        )
        await session.commit()

        executed_at = datetime.now(UTC)
        updated = await repo.mark_tombstone_executed(
            evidence.id, "tenant-tombstone-exec", executed_at
        )
        await session.commit()
        assert updated.executed_at == executed_at

        refetched = await repo.get_tombstone(evidence.id, "tenant-tombstone-exec")
        assert refetched is not None
        assert refetched.executed_at == executed_at


async def test_mark_tombstone_executed_raises_when_no_tombstone_exists() -> None:
    async with session_factory() as session:
        repo = SqlAlchemyEvidenceRepository(session)
        with pytest.raises(TombstoneNotFoundError):
            await repo.mark_tombstone_executed(uuid4(), "tenant-none", datetime.now(UTC))


async def test_mark_tombstone_executed_raises_across_tenant_boundary() -> None:
    """A resource ID alone must never be sufficient authorization context,
    even for a narrow transition method."""
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-tombstone-exec-iso")
        evidence = await _create_evidence(session, "tenant-tombstone-exec-iso", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        await repo.add_tombstone(
            EvidenceTombstone(
                evidence_id=evidence.id,
                session_id=UUID(session_id),
                tenant_id="tenant-tombstone-exec-iso",
                deletion_basis=DeletionBasis.TENANT_REQUEST,
                authorized_by="admin-1",
                evidence_integrity_reference=evidence.checksum,
            )
        )
        await session.commit()

        with pytest.raises(TombstoneNotFoundError):
            await repo.mark_tombstone_executed(
                evidence.id, "some-other-tenant", datetime.now(UTC)
            )


async def test_delete_content_is_idempotent() -> None:
    """The decisive reconciliation-safety primitive: object/row-absent must
    be treated as already satisfied, never as an error, on retry."""
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-delete-content")
        evidence = await _create_evidence(session, "tenant-delete-content", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        first = await repo.delete_content(evidence.id, "tenant-delete-content")
        await session.commit()
        assert first is True

        second = await repo.delete_content(evidence.id, "tenant-delete-content")
        await session.commit()
        assert second is False

        assert await repo.get(evidence.id, "tenant-delete-content") is None


async def test_delete_content_is_tenant_scoped() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-delete-iso-a")
        evidence = await _create_evidence(session, "tenant-delete-iso-a", session_id)
        repo = SqlAlchemyEvidenceRepository(session)

        deleted = await repo.delete_content(evidence.id, "tenant-delete-iso-b")
        await session.commit()
        assert deleted is False
        assert await repo.get(evidence.id, "tenant-delete-iso-a") is not None


async def test_list_expired_is_tenant_scoped() -> None:
    """Tenant IDs are scoped per test run (not fixed literals): these
    integration tests commit against real Postgres and are not
    transaction-rolled-back between runs, so a fixed tenant literal would
    accumulate rows across repeated runs and break exact-membership
    assertions."""
    async with session_factory() as session:
        tenant_a = f"tenant-expired-a-{uuid4()}"
        tenant_b = f"tenant-expired-b-{uuid4()}"
        past = datetime.now(UTC) - timedelta(days=1)
        session_id_a = await _create_session(session, tenant_a)
        session_id_b = await _create_session(session, tenant_b)
        evidence_a = await _create_evidence(session, tenant_a, session_id_a, retention_until=past)
        await _create_evidence(session, tenant_b, session_id_b, retention_until=past)
        await session.commit()

        repo = SqlAlchemyEvidenceRepository(session)
        expired_for_a = await repo.list_expired(tenant_a, datetime.now(UTC))
        assert {e.id for e in expired_for_a} == {evidence_a.id}


async def test_list_expired_respects_as_of_boundary() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-expired-boundary")
        future_retention = datetime.now(UTC) + timedelta(days=30)
        evidence = await _create_evidence(
            session, "tenant-expired-boundary", session_id, retention_until=future_retention
        )
        await session.commit()

        repo = SqlAlchemyEvidenceRepository(session)

        not_yet = await repo.list_expired("tenant-expired-boundary", datetime.now(UTC))
        assert evidence.id not in {e.id for e in not_yet}

        after_future_as_of = await repo.list_expired(
            "tenant-expired-boundary", future_retention + timedelta(seconds=1)
        )
        assert evidence.id in {e.id for e in after_future_as_of}


async def test_list_expired_excludes_already_tombstoned() -> None:
    async with session_factory() as session:
        past = datetime.now(UTC) - timedelta(days=1)
        session_id = await _create_session(session, "tenant-expired-requested")
        evidence = await _create_evidence(
            session, "tenant-expired-requested", session_id, retention_until=past
        )
        repo = SqlAlchemyEvidenceRepository(session)
        await repo.add_tombstone(
            EvidenceTombstone(
                evidence_id=evidence.id,
                session_id=UUID(session_id),
                tenant_id="tenant-expired-requested",
                deletion_basis=DeletionBasis.RETENTION_EXPIRY,
                authorized_by="system",
                evidence_integrity_reference=evidence.checksum,
            )
        )
        await session.commit()

        expired = await repo.list_expired("tenant-expired-requested", datetime.now(UTC))
        assert evidence.id not in {e.id for e in expired}


async def test_evidence_tombstones_table_has_no_sensitive_columns() -> None:
    """Structural proof against the real schema, not just the domain model
    (PRV-11.30.1): the persisted table itself has no column shaped to hold
    raw content."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'evidence_tombstones'"
            )
        )
        columns = {row[0] for row in result.all()}
        forbidden = {"content", "image", "bytes", "object_key", "mime_type", "size_bytes"}
        assert columns.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# Evidence-result tombstones
# ---------------------------------------------------------------------------


async def test_evidence_result_add_and_get_tombstone_round_trips() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-result-tombstone")
        result = await _create_evidence_result(session, "tenant-result-tombstone", session_id)
        repo = SqlAlchemyEvidenceResultRepository(
            session, LocalAesGcmKeyProvider({"k": b"0" * 32}), "k"
        )

        await repo.add_tombstone(
            EvidenceResultTombstone(
                evidence_result_id=result.id,
                session_id=UUID(session_id),
                tenant_id="tenant-result-tombstone",
                deletion_basis=DeletionBasis.DATA_SUBJECT_REQUEST,
                authorized_by="admin-1",
                evidence_integrity_reference=result.integrity_reference,
            )
        )
        await session.commit()

        fetched = await repo.get_tombstone(result.id, "tenant-result-tombstone")
        assert fetched is not None
        assert fetched.executed_at is None


async def test_evidence_result_duplicate_tombstone_creation_is_rejected() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-result-tombstone-dup")
        result = await _create_evidence_result(
            session, "tenant-result-tombstone-dup", session_id
        )
        repo = SqlAlchemyEvidenceResultRepository(
            session, LocalAesGcmKeyProvider({"k": b"0" * 32}), "k"
        )

        def _make_tombstone() -> EvidenceResultTombstone:
            return EvidenceResultTombstone(
                evidence_result_id=result.id,
                session_id=UUID(session_id),
                tenant_id="tenant-result-tombstone-dup",
                deletion_basis=DeletionBasis.TENANT_REQUEST,
                authorized_by="admin-1",
                evidence_integrity_reference=result.integrity_reference,
            )

        await repo.add_tombstone(_make_tombstone())
        await session.commit()

        with pytest.raises(DeletionAlreadyRequestedError):
            await repo.add_tombstone(_make_tombstone())
        await session.rollback()


async def test_evidence_result_delete_content_is_idempotent() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-result-delete")
        result = await _create_evidence_result(session, "tenant-result-delete", session_id)
        repo = SqlAlchemyEvidenceResultRepository(
            session, LocalAesGcmKeyProvider({"k": b"0" * 32}), "k"
        )

        first = await repo.delete_content(result.id, "tenant-result-delete")
        await session.commit()
        assert first is True

        second = await repo.delete_content(result.id, "tenant-result-delete")
        await session.commit()
        assert second is False

        assert await repo.get(result.id, "tenant-result-delete") is None


async def test_evidence_result_list_expired_excludes_already_tombstoned() -> None:
    async with session_factory() as session:
        past = datetime.now(UTC) - timedelta(days=1)
        session_id = await _create_session(session, "tenant-result-expired")
        result = await _create_evidence_result(
            session, "tenant-result-expired", session_id, retention_until=past
        )
        repo = SqlAlchemyEvidenceResultRepository(
            session, LocalAesGcmKeyProvider({"k": b"0" * 32}), "k"
        )

        expired_before = await repo.list_expired("tenant-result-expired", datetime.now(UTC))
        assert result.id in {r.id for r in expired_before}

        await repo.add_tombstone(
            EvidenceResultTombstone(
                evidence_result_id=result.id,
                session_id=UUID(session_id),
                tenant_id="tenant-result-expired",
                deletion_basis=DeletionBasis.RETENTION_EXPIRY,
                authorized_by="system",
                evidence_integrity_reference=result.integrity_reference,
            )
        )
        await session.commit()

        expired_after = await repo.list_expired("tenant-result-expired", datetime.now(UTC))
        assert result.id not in {r.id for r in expired_after}


async def test_evidence_result_tombstones_table_has_no_result_column() -> None:
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'evidence_result_tombstones'"
            )
        )
        columns = {row[0] for row in result.all()}
        assert "result" not in columns
        assert "result_json" not in columns
        assert "result_ciphertext" not in columns
