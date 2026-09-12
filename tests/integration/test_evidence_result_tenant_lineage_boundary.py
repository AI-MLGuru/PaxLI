"""WF-HV-009's final confirmatory check: the cross-TENANT case of the two
lineage operations Findings A and B already fixed.

Finding A's regression coverage (test_evidence_result_supersession_
integrity.py) and Finding B's (test_evidence_result_service.py) both
prove their fix against a cross-SESSION, SAME-tenant attacker -- neither
exercises an attacker in a genuinely different tenant. The underlying
fixes are already tenant-scoped by construction (mark_not_effective()'s
CAS UPDATE includes tenant_id in its WHERE clause; _validate_provenance()
fetches through tenant-scoped repository.get() calls), so no new defect
is expected here -- this closes the coverage gap, not a code gap,
confirming the single invariant that connects both prior findings:

    An EvidenceResult mutation or lineage operation MUST be incapable
    of crossing either the tenant boundary or the session boundary.

Confirmed live via a temporary probe before writing this permanent
version: both attacks below were already correctly rejected by the
existing Finding A/B fixes, with the victim's evidence provably
untouched in both cases.

Skipped when Postgres isn't reachable, mirroring
tests/integration/test_evidence_result_supersession_integrity.py.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.exceptions import (
    InvalidProvenanceReferenceError,
    InvalidSupersessionError,
)
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


def _service(session, key_provider, key_id) -> EvidenceResultService:
    repo = SqlAlchemyEvidenceResultRepository(session, key_provider, key_id)
    return EvidenceResultService(
        repo,
        AuditService(SqlAlchemyAuditEventRepository(session)),
        SqlAlchemyEvidenceRepository(session),
    )


async def test_cross_tenant_supersession_is_rejected_and_victim_survives() -> None:
    """Tenant B attempts to supersede Tenant A's effective EvidenceResult.
    Must fail with InvalidSupersessionError; Tenant A's result must
    remain effective and untouched."""
    tenant_victim = f"tenant-victim-lineage-super-{uuid4()}"
    tenant_attacker = f"tenant-attacker-lineage-super-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-hv009-lineage-key": b"0" * 32})
    key_id = "test-hv009-lineage-key"

    async with session_factory() as session:
        victim_session_id = await _create_session(session, tenant_victim)
        attacker_session_id = await _create_session(session, tenant_attacker)
        svc = _service(session, key_provider, key_id)
        victim = await svc.create(
            tenant_id=tenant_victim,
            session_id=UUID(victim_session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session, key_provider, key_id)
        with pytest.raises(InvalidSupersessionError):
            await svc.supersede(
                evidence_result_id=victim.id,
                tenant_id=tenant_attacker,
                session_id=UUID(attacker_session_id),
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="attacker",
                producer_version="1",
            )
        await session.rollback()

    async with session_factory() as session:
        svc = _service(session, key_provider, key_id)
        # Victim's evidence is untouched -- still the sole effective result.
        effective_victim = await svc.list_effective_for_session(
            session_id=UUID(victim_session_id), tenant_id=tenant_victim
        )
        assert [r.id for r in effective_victim] == [victim.id]
        assert effective_victim[0].status == EvidenceResultStatus.PASS  # never mutated

        # Attacker's tenant has no evidence at all -- no fabricated row.
        effective_attacker = await svc.list_effective_for_session(
            session_id=UUID(attacker_session_id), tenant_id=tenant_attacker
        )
        assert effective_attacker == []


async def test_cross_tenant_provenance_reference_is_rejected_and_creates_nothing() -> None:
    """Tenant B attempts to create a result for its own session that
    claims lineage (parent_evidence_result_ids) from Tenant A's real
    result. Must fail with InvalidProvenanceReferenceError; no result is
    persisted for Tenant B, and Tenant A's result is untouched."""
    tenant_victim = f"tenant-victim-lineage-prov-{uuid4()}"
    tenant_attacker = f"tenant-attacker-lineage-prov-{uuid4()}"
    key_provider = LocalAesGcmKeyProvider({"test-hv009-lineage-key2": b"0" * 32})
    key_id = "test-hv009-lineage-key2"

    async with session_factory() as session:
        victim_session_id = await _create_session(session, tenant_victim)
        attacker_session_id = await _create_session(session, tenant_attacker)
        svc = _service(session, key_provider, key_id)
        victim_result = await svc.create(
            tenant_id=tenant_victim,
            session_id=UUID(victim_session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session, key_provider, key_id)
        with pytest.raises(InvalidProvenanceReferenceError):
            await svc.create(
                tenant_id=tenant_attacker,
                session_id=UUID(attacker_session_id),
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="attacker",
                producer_version="1",
                parent_evidence_result_ids=(victim_result.id,),
            )
        await session.rollback()

    async with session_factory() as session:
        svc = _service(session, key_provider, key_id)
        # No forged row for the attacker's tenant/session.
        effective_attacker = await svc.list_effective_for_session(
            session_id=UUID(attacker_session_id), tenant_id=tenant_attacker
        )
        assert effective_attacker == []

        # Victim's result survives, unrelated to any attacker lineage.
        effective_victim = await svc.list_effective_for_session(
            session_id=UUID(victim_session_id), tenant_id=tenant_victim
        )
        assert [r.id for r in effective_victim] == [victim_result.id]
