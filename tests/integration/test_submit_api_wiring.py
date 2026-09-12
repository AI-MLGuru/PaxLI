"""Real PostgreSQL proof for WF-005's own new surface specifically: the
FastAPI dependency-provider functions apps/api/paxli_api/dependencies.py
adds (get_workflow_service, get_decision_persistence_service), driven
directly rather than through the abstract service classes
tests/integration/test_verification_workflow.py already exhaustively
proves. That file proves VerificationWorkflowService itself is correct;
this file proves the NEW DI wiring the router actually depends on
constructs a working instance and behaves identically under a genuine
concurrent race, closing the gap between "the class works" and "the way
the router actually obtains it works." Skipped when Postgres isn't
reachable.
"""

import asyncio
import socket
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from apps.api.paxli_api.dependencies import (
    get_decision_persistence_service,
    get_workflow_service,
)
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel, VerificationStatus
from core.verification.service import VerificationSessionService
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
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


async def _activate_policy(tenant_id: str) -> None:
    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-wf005-wiring",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            default_outcome=DecisionOutcome.INCONCLUSIVE,
        )
        await session.commit()


async def _create_session(tenant_id: str) -> UUID:
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
        created = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()
    return created.id


async def test_workflow_service_di_wiring_completes_a_submission() -> None:
    """get_workflow_service()/get_decision_persistence_service(), driven
    exactly as FastAPI would drive them, against real Postgres: a session
    submitted through the DI-constructed VerificationWorkflowService
    reaches COMPLETED with a decision, and that SAME decision is what the
    DI-constructed DecisionPersistenceService (the GET endpoint's own
    dependency) reads back."""
    tenant_id = f"tenant-wf005-wiring-{uuid4()}"
    await _activate_policy(tenant_id)
    session_id = await _create_session(tenant_id)

    async with session_factory() as db_session:
        workflow_service = await anext(
            get_workflow_service(db_session=db_session, settings=get_settings())
        )
        result_session, decision = await workflow_service.submit(
            session_id=session_id, tenant_id=tenant_id
        )
        await db_session.commit()

    assert result_session.status is VerificationStatus.COMPLETED
    assert decision.outcome is DecisionOutcome.INCONCLUSIVE

    async with session_factory() as db_session:
        decision_service = await anext(
            get_decision_persistence_service(db_session=db_session)
        )
        read_back = await decision_service.get_for_session(
            session_id=session_id, tenant_id=tenant_id
        )

    assert read_back is not None
    assert read_back.decision_id == decision.decision_id


async def test_workflow_service_di_wiring_concurrent_submit_converges() -> None:
    """The same barrier-synchronized race
    test_verification_workflow.py's test_concurrent_submit_from_created_
    converges_on_one_decision proves against the abstract service class,
    proven again here specifically through get_workflow_service() -- the
    exact function the router calls via Depends()."""
    tenant_id = f"tenant-wf005-wiring-race-{uuid4()}"
    await _activate_policy(tenant_id)
    session_id = await _create_session(tenant_id)
    first_started = asyncio.Event()

    async def _submit_attempt(*, wait_for_signal: bool, delay_before_commit: float) -> UUID:
        async with session_factory() as db_session:
            workflow_service = await anext(
                get_workflow_service(db_session=db_session, settings=get_settings())
            )
            if wait_for_signal:
                await first_started.wait()
            try:
                _session, decision = await workflow_service.submit(
                    session_id=session_id, tenant_id=tenant_id
                )
            finally:
                if not wait_for_signal:
                    first_started.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await db_session.commit()
            return decision.decision_id

    decision_ids = await asyncio.gather(
        _submit_attempt(wait_for_signal=False, delay_before_commit=0.5),
        _submit_attempt(wait_for_signal=True, delay_before_commit=0.0),
    )

    assert decision_ids[0] == decision_ids[1]

    async with session_factory() as db_session:
        decision_service = await anext(
            get_decision_persistence_service(db_session=db_session)
        )
        read_back = await decision_service.get_for_session(
            session_id=session_id, tenant_id=tenant_id
        )
    assert read_back is not None
    assert read_back.decision_id == decision_ids[0]
