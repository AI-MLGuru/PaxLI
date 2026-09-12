"""WF-006 Finding B / WF-4.6.4 / WF-4.17.4: real-Postgres proof that the
EXPIRED transition's required audit event is durably persisted by
VerificationSessionService.get() itself, not merely by a specific
caller's own ad hoc check. Skipped when Postgres isn't reachable,
mirroring tests/integration/test_evidence_result_persistence.py's
pattern.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from apps.api.paxli_api.config import get_settings
from core.audit.enums import AuditEventType
from core.audit.service import AuditService
from core.verification.enums import VerificationStatus
from core.verification.service import VerificationSessionService
from infrastructure.database.models.audit_event import AuditEventRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory


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


async def _create_expired_session(tenant_id: str) -> UUID:
    session_id = uuid4()
    async with session_factory() as session:
        session.add(
            VerificationSessionRecord(
                id=str(session_id),
                tenant_id=tenant_id,
                status=VerificationStatus.CREATED.value,
                assurance_level="STANDARD",
                created_at=datetime.now(UTC) - timedelta(hours=2),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()
    return session_id


async def test_get_durably_persists_the_session_expired_audit_event() -> None:
    tenant_id = f"tenant-expiry-audit-{uuid4()}"
    session_id = await _create_expired_session(tenant_id)

    async with session_factory() as session:
        service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
        )
        fetched = await service.get(session_id=session_id, tenant_id=tenant_id)
        assert fetched.status is VerificationStatus.EXPIRED
        await session.commit()

    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.session_id == str(session_id),
                    AuditEventRecord.event_type == AuditEventType.SESSION_EXPIRED.value,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].tenant_id == tenant_id


async def test_repeated_get_never_duplicates_the_durable_audit_row() -> None:
    tenant_id = f"tenant-expiry-audit-repeat-{uuid4()}"
    session_id = await _create_expired_session(tenant_id)

    for _ in range(3):
        async with session_factory() as session:
            service = VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                AuditService(SqlAlchemyAuditEventRepository(session)),
            )
            await service.get(session_id=session_id, tenant_id=tenant_id)
            await session.commit()

    async with session_factory() as verify_session:
        rows = (
            await verify_session.execute(
                select(AuditEventRecord).where(
                    AuditEventRecord.session_id == str(session_id),
                    AuditEventRecord.event_type == AuditEventType.SESSION_EXPIRED.value,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
