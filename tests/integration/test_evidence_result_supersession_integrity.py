"""WF-HV-009 Finding A: real-Postgres proof that
EvidenceResultService.supersede() cannot be used to deactivate another
session's effective evidence.

Before this fix, `supersede()` never validated its `evidence_result_id`
argument -- it trusted the caller's claimed session_id/evidence_type and
called `mark_not_effective(evidence_result_id, tenant_id)`, which itself
only scoped by tenant_id. A same-tenant caller acting on behalf of
session B, but supplying a same-tenant EvidenceResult ID that actually
belonged to session A, would silently flip session A's legitimate,
unrelated result to is_effective=False -- confirmed live: session A's
effective-evidence set (the Decision Engine's own input) went from
[victim] to [] with no error raised anywhere.

The fix makes the underlying mutation a single atomically-arbitrated
UPDATE ... WHERE id = ? AND tenant_id = ? AND session_id = ? AND
evidence_type = ? AND is_effective = true (the same CAS pattern used by
every lifecycle transition in this codebase), and supersede() now
raises InvalidSupersessionError when zero rows match -- proven here
against a real database, not merely against the in-memory fake used by
tests/unit/test_evidence_result_service.py's equivalent scenarios.

Skipped when Postgres isn't reachable, mirroring
tests/integration/test_evidence_result_persistence.py.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import InvalidSupersessionError
from core.evidence_result.service import EvidenceResultService
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
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


def _service(session) -> EvidenceResultService:
    key_provider = LocalAesGcmKeyProvider({"test-hv009-key": b"0" * 32})
    repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-hv009-key")
    return EvidenceResultService(
        repo,
        AuditService(SqlAlchemyAuditEventRepository(session)),
        SqlAlchemyEvidenceRepository(session),
    )


async def test_supersede_cannot_deactivate_another_sessions_effective_evidence() -> None:
    """The exact attack confirmed live during HV-009: session B's own
    (would-be) supersede() call names session A's real EvidenceResult ID.
    Must be rejected outright, leaving session A's result untouched and
    creating no row for session B."""
    tenant_id = f"tenant-hv009-cross-session-{uuid4()}"

    async with session_factory() as session:
        session_a_id = await _create_session(session, tenant_id)
        session_b_id = await _create_session(session, tenant_id)
        svc = _service(session)

        victim = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_a_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session)
        with pytest.raises(InvalidSupersessionError):
            await svc.supersede(
                evidence_result_id=victim.id,
                tenant_id=tenant_id,
                session_id=UUID(session_b_id),
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="attacker-producer",
                producer_version="1.0",
            )
        await session.rollback()

    # Session A's evidence survives, untouched, still the sole effective
    # result -- read back from a fresh session, not the in-memory object.
    async with session_factory() as session:
        svc = _service(session)
        effective_a = await svc.list_effective_for_session(
            session_id=UUID(session_a_id), tenant_id=tenant_id
        )
        assert [r.id for r in effective_a] == [victim.id]
        assert effective_a[0].status == EvidenceResultStatus.PASS  # never mutated

        # Session B has no evidence at all -- no fabricated/attacker row.
        effective_b = await svc.list_effective_for_session(
            session_id=UUID(session_b_id), tenant_id=tenant_id
        )
        assert effective_b == []


async def test_supersede_against_real_postgres_rejects_wrong_evidence_type() -> None:
    """Same CAS predicate, attacked on the evidence_type dimension instead
    of session_id -- the database-level WHERE clause must match all four
    fields, not just id/tenant_id."""
    tenant_id = f"tenant-hv009-wrong-type-{uuid4()}"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        svc = _service(session)
        original = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session)
        with pytest.raises(InvalidSupersessionError):
            await svc.supersede(
                evidence_result_id=original.id,
                tenant_id=tenant_id,
                session_id=UUID(session_id),
                evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
                status=EvidenceResultStatus.PASS,
                producer="face-provider",
                producer_version="1.1",
            )
        await session.rollback()

    async with session_factory() as session:
        svc = _service(session)
        effective = await svc.list_effective_for_session(
            session_id=UUID(session_id), tenant_id=tenant_id
        )
        assert [r.id for r in effective] == [original.id]


async def test_supersede_is_role_local_reference_retry_never_touches_probe() -> None:
    """BD-001.4/BD-001.5 (Slice H): the literal demonstration of "role is
    part of evidence identity; retry is versioning within that role."
    Superseding FACE_EMBEDDING_REFERENCE must not affect a
    simultaneously-effective FACE_EMBEDDING_PROBE row for the same
    session -- they are different evidence_type values, not two
    versions of the same one."""
    tenant_id = f"tenant-h1-role-local-supersession-{uuid4()}"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        svc = _service(session)

        reference_v1 = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": [0.1, 0.2, 0.3], "embedding_dimensions": 3},
        )
        probe = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": [0.4, 0.5, 0.6], "embedding_dimensions": 3},
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session)
        reference_v2 = await svc.supersede(
            evidence_result_id=reference_v1.id,
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.1",
            result={"embedding": [0.7, 0.8, 0.9], "embedding_dimensions": 3},
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session)
        effective = await svc.list_effective_for_session(
            session_id=UUID(session_id), tenant_id=tenant_id
        )
        effective_by_type = {r.evidence_type: r for r in effective}
        # Exactly two effective rows -- reference's replacement and the
        # untouched probe -- never three, never one.
        assert len(effective) == 2
        assert (
            effective_by_type[EvidenceResultType.FACE_EMBEDDING_REFERENCE].id == reference_v2.id
        )
        assert effective_by_type[EvidenceResultType.FACE_EMBEDDING_PROBE].id == probe.id
        assert (
            effective_by_type[EvidenceResultType.FACE_EMBEDDING_PROBE].result
            == {"embedding": [0.4, 0.5, 0.6], "embedding_dimensions": 3}
        )
