"""Real PostgreSQL integration tests for Foundation-009 (Policy Governance
Infrastructure). Skipped when Postgres isn't reachable, mirroring
tests/integration/test_evidence_result_persistence.py's pattern.
"""

import asyncio
import socket
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.api.averiq_api.config import get_settings
from core.audit.service import AuditService
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.policy.enums import PolicyStatus
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from infrastructure.database.models.audit_event import AuditEventRecord
from infrastructure.database.models.policy import PolicyRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
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


def _service(session) -> PolicyService:
    return PolicyService(
        SqlAlchemyVerificationPolicyRepository(session),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        EvidenceResultSchemaCatalog(),
    )


async def test_repeated_idempotency_key_against_real_postgres_creates_one_version() -> None:
    """Invariant-12 remediation, end to end against real Postgres: a
    retried activation request (same tenant, same idempotency_key) must
    resolve to the same version -- proving both the uq_policies_tenant_
    idempotency constraint and the audit dedupe_key work together, not
    just in the in-memory unit test."""
    tenant_id = f"tenant-policy-idem-{uuid4()}"
    async with session_factory() as session:
        svc = _service(session)
        first = await svc.create_and_activate(
            tenant_id=tenant_id,
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            thresholds={"pass": 0.9},
            idempotency_key="req-xyz",
        )
        await session.commit()

    async with session_factory() as session:
        svc = _service(session)
        second = await svc.create_and_activate(
            tenant_id=tenant_id,
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            thresholds={"pass": 0.9},
            idempotency_key="req-xyz",
        )
        await session.commit()

    assert first.id == second.id
    assert first.version == second.version == 1

    async with session_factory() as session:
        rows = (
            (await session.execute(select(PolicyRecord).where(PolicyRecord.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1  # only one real version was ever persisted

        audit_rows = (
            (
                await session.execute(
                    select(AuditEventRecord).where(AuditEventRecord.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        # the dedupe_key constraint means the retry's audit call resolved
        # to the existing event rather than inserting a second one
        assert len(audit_rows) == 1


async def test_partial_unique_index_rejects_two_active_rows_direct_insert() -> None:
    """Direct proof against real PostgreSQL that the partial unique index
    is enforced at the database level, not application code alone."""
    async with session_factory() as session:
        session.add(
            PolicyRecord(
                id="11111111-1111-1111-1111-111111111111",
                policy_id="kyc-a",
                version=1,
                tenant_id="tenant-policy-index-test",
                assurance_level="STANDARD",
                schema_version="1.0",
                status="ACTIVE",
                evidence_requirements_json={},
                gates_json=[],
                rules_json=[],
                thresholds_json={},
                metadata_json={},
                canonical_hash="hash-1",
                created_at=datetime.now(UTC),
                activated_at=datetime.now(UTC),
                created_by="admin",
            )
        )
        await session.flush()
        session.add(
            PolicyRecord(
                id="22222222-2222-2222-2222-222222222222",
                policy_id="kyc-b",
                version=1,
                tenant_id="tenant-policy-index-test",
                assurance_level="STANDARD",
                schema_version="1.0",
                status="ACTIVE",
                evidence_requirements_json={},
                gates_json=[],
                rules_json=[],
                thresholds_json={},
                metadata_json={},
                canonical_hash="hash-2",
                created_at=datetime.now(UTC),
                activated_at=datetime.now(UTC),
                created_by="admin",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_create_and_activate_persists_and_audits() -> None:
    async with session_factory() as session:
        svc = _service(session)
        policy = await svc.create_and_activate(
            tenant_id="tenant-policy-create",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            thresholds={"pass": 0.9},
        )
        await session.commit()

        record = await session.get(PolicyRecord, str(policy.id))
        assert record is not None
        assert record.status == "ACTIVE"

        audit_records = (
            (
                await session.execute(
                    select(AuditEventRecord).where(
                        AuditEventRecord.tenant_id == "tenant-policy-create"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(r.event_type == "POLICY_ACTIVATED" for r in audit_records)


async def test_cross_tenant_get_returns_none() -> None:
    async with session_factory() as session:
        svc = _service(session)
        policy = await svc.create_and_activate(
            tenant_id="tenant-policy-iso-a",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
        )
        await session.commit()

        repo = SqlAlchemyVerificationPolicyRepository(session)
        assert await repo.get(policy.id, "tenant-policy-iso-b") is None
        assert await repo.get(policy.id, "tenant-policy-iso-a") is not None


async def test_second_activation_supersedes_the_first_against_real_postgres() -> None:
    async with session_factory() as session:
        svc = _service(session)
        first = await svc.create_and_activate(
            tenant_id="tenant-policy-supersede",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
        )
        await session.commit()

        second = await svc.create_and_activate(
            tenant_id="tenant-policy-supersede",
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            thresholds={"pass": 0.99},
        )
        await session.commit()

        repo = SqlAlchemyVerificationPolicyRepository(session)
        stored_first = await repo.get(first.id, "tenant-policy-supersede")
        assert stored_first is not None
        assert stored_first.status == PolicyStatus.SUPERSEDED
        assert second.status == PolicyStatus.ACTIVE
        assert second.supersedes_id == first.id


async def test_rollback_creates_a_new_version_original_untouched() -> None:
    # A fresh tenant_id per run: version numbers are relative to whatever a
    # policy_id already has for a tenant, so a fixed tenant_id would make
    # this test's absolute version assertions depend on accumulated state
    # from earlier runs against the same database.
    tenant_id = f"tenant-policy-rollback-{uuid4()}"
    async with session_factory() as session:
        svc = _service(session)
        v1 = await svc.create_and_activate(
            tenant_id=tenant_id,
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            thresholds={"pass": 0.9},
        )
        await session.commit()

        v2 = await svc.create_and_activate(
            tenant_id=tenant_id,
            policy_id="kyc-standard",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin-1",
            thresholds={"pass": 0.99},
        )
        await session.commit()

        v3 = await svc.rollback(
            tenant_id=tenant_id,
            policy_id="kyc-standard",
            target_version=v1.version,
            created_by="admin-2",
        )
        await session.commit()

        repo = SqlAlchemyVerificationPolicyRepository(session)
        stored_v1 = await repo.get(v1.id, tenant_id)
        assert stored_v1 is not None
        assert stored_v1.id == v1.id
        assert stored_v1.version == v1.version
        assert stored_v1.status == PolicyStatus.SUPERSEDED  # superseded by v2, never reactivated

        assert v3.id != v1.id
        assert v3.version == v2.version + 1
        assert v3.status == PolicyStatus.ACTIVE
        assert v3.canonical_hash == v1.canonical_hash


async def test_concurrent_activation_for_the_same_applicability_one_wins_one_conflicts() -> None:
    """Foundation-009 discovery question 8: two administrators racing to
    activate a policy for the same (tenant_id, assurance_level). Each runs
    in its own session/transaction; the database's partial unique index
    resolves the race, never an application-level check-then-insert.

    A plain `asyncio.gather` of two full `create_and_activate` calls is not
    reliable proof by itself: against a fast local Postgres, one coroutine
    can run flush-through-commit to completion before the other's first
    await is even scheduled, so the two transactions never actually
    overlap and neither observes a conflict (confirmed by first running
    this test without the barrier below -- both attempts reported "won").
    An asyncio.Event forces the second transaction's INSERT to genuinely
    start while the first's is still open and uncommitted, so PostgreSQL's
    real index-level locking -- not scheduling luck -- is what resolves it.
    """
    tenant_id = "tenant-policy-race"
    assurance_level = AssuranceLevel.STANDARD.value
    first_inserted = asyncio.Event()

    async def _insert_active(policy_id: str, *, wait_for_signal: bool, delay_before_commit: float):
        async with session_factory() as session:
            session.add(
                PolicyRecord(
                    id=str(uuid4()),
                    policy_id=policy_id,
                    version=1,
                    tenant_id=tenant_id,
                    assurance_level=assurance_level,
                    schema_version="1.0",
                    status="ACTIVE",
                    evidence_requirements_json={},
                    gates_json=[],
                    rules_json=[],
                    thresholds_json={},
                    metadata_json={},
                    canonical_hash=f"hash-{policy_id}",
                    created_at=datetime.now(UTC),
                    activated_at=datetime.now(UTC),
                    created_by="admin",
                )
            )
            if wait_for_signal:
                await first_inserted.wait()
            try:
                try:
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    return "conflict"
            finally:
                # Always release the barrier, even if this attempt's own
                # flush failed for an unrelated reason (e.g. leftover test
                # data) -- otherwise a waiting sibling task hangs forever
                # on an event that never gets set.
                if not wait_for_signal:
                    first_inserted.set()
            if delay_before_commit:
                await asyncio.sleep(delay_before_commit)
            await session.commit()
            return "won"

    async with session_factory() as setup_session:
        # remove ANY leftover row for this tenant from a prior run of this
        # test, not just ACTIVE ones -- a SUPERSEDED row with the same
        # (tenant_id, policy_id, version) would otherwise collide with
        # uq_policies_tenant_version and fail this test for a reason
        # unrelated to the race being proven here.
        existing = (
            (
                await setup_session.execute(
                    select(PolicyRecord).where(PolicyRecord.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        for row in existing:
            await setup_session.delete(row)
        await setup_session.commit()

    results = await asyncio.gather(
        _insert_active("kyc-a", wait_for_signal=False, delay_before_commit=0.5),
        _insert_active("kyc-b", wait_for_signal=True, delay_before_commit=0.0),
    )
    assert sorted(results) == ["conflict", "won"]
