"""Real PostgreSQL integration tests for Foundation-008 (Evidence Result
Model & Persistence). Skipped when Postgres isn't reachable, mirroring
tests/integration/test_migrations.py's pattern.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence_result.classification import DataClassification, classify
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.service import EvidenceResultService
from infrastructure.database.models.evidence_result import EvidenceResultRecord
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


async def test_check_constraint_rejects_both_representations_populated() -> None:
    """Direct proof against real PostgreSQL that the XOR invariant is
    enforced at the database level, not application code alone."""
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-constraint-test")
        session.add(
            EvidenceResultRecord(
                id=str(uuid4()),
                tenant_id="tenant-constraint-test",
                session_id=session_id,
                evidence_type="FACE_MATCH",
                schema_version="1.0",
                status="PASS",
                result_json={"a": 1},
                result_ciphertext=b"should-not-coexist-with-json",
                reason_codes_json=[],
                producer="p",
                producer_version="1",
                parent_evidence_result_ids_json=[],
                produced_at=datetime.now(UTC),
                persisted_at=datetime.now(UTC),
                integrity_reference="deadbeef",
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_sensitive_result_round_trips_as_plain_json_in_db() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-persist-plain")
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        saved = await svc.create(
            tenant_id="tenant-persist-plain",
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"similarity": 0.77},
            score=0.77,
        )
        await session.commit()

        record = await session.get(EvidenceResultRecord, str(saved.id))
        assert record is not None
        assert record.result_json == {"similarity": 0.77}
        assert record.result_ciphertext is None

        fetched = await repo.get(saved.id, "tenant-persist-plain")
        assert fetched is not None
        assert fetched.result == {"similarity": 0.77}


async def test_highly_sensitive_result_is_encrypted_at_rest_and_round_trips() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-persist-encrypted")
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        canary_embedding = [0.123456, 0.654321, 0.999999]
        saved = await svc.create(
            tenant_id="tenant-persist-encrypted",
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_EMBEDDING,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": canary_embedding, "embedding_dimensions": 3},
        )
        await session.commit()

        record = await session.get(EvidenceResultRecord, str(saved.id))
        assert record is not None
        assert record.result_json is None
        assert record.result_ciphertext is not None
        assert record.result_key_id == "test-evidence-result-key"
        # the raw stored bytes must not contain the plaintext canary values
        for value in canary_embedding:
            assert str(value).encode() not in record.result_ciphertext

        fetched = await repo.get(saved.id, "tenant-persist-encrypted")
        assert fetched is not None
        assert fetched.result == {"embedding": canary_embedding, "embedding_dimensions": 3}


@pytest.mark.parametrize(
    "evidence_type",
    [
        EvidenceResultType.OCR_EXTRACTION,
        EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
        EvidenceResultType.MRZ,
        EvidenceResultType.BARCODE_QR,
    ],
)
async def test_document_extraction_types_are_highly_sensitive_and_encrypted_at_rest(
    evidence_type: EvidenceResultType,
) -> None:
    """HV-010: DP-001 Decision 1 classifies OCR_EXTRACTION, MRZ, BARCODE_QR,
    and DOCUMENT_FIELD_EXTRACTION as HIGHLY_SENSITIVE -- they carry raw or
    reconciled identity-field VALUES, unlike DOCUMENT_QUALITY/
    DOCUMENT_CLASSIFICATION's category-only outputs (Phase 1's own two
    producers). No Phase 2+ capability writes these types yet, so nothing
    has ever actually exercised the classification->encryption wiring for
    them -- confirmed directly here rather than assumed from the
    classification map alone, the same way test_highly_sensitive_result_
    is_encrypted_at_rest_and_round_trips already confirms it for
    FACE_EMBEDDING."""
    assert classify(evidence_type) == DataClassification.HIGHLY_SENSITIVE

    canary_value = f"CANARY-IDENTITY-VALUE-{uuid4()}"
    # Each type's registered result schema (core.evidence_result.schemas)
    # requires different fields -- a generic payload would fail schema
    # validation before ever reaching the encryption boundary this test
    # targets, so the canary is embedded in whatever shape each type
    # actually requires.
    payload_by_type = {
        EvidenceResultType.OCR_EXTRACTION: {"fields": {"surname": canary_value}},
        EvidenceResultType.DOCUMENT_FIELD_EXTRACTION: {"fields": {"surname": canary_value}},
        EvidenceResultType.MRZ: {"raw": canary_value, "fields": {"surname": canary_value}},
        EvidenceResultType.BARCODE_QR: {"raw": canary_value, "fields": {}},
    }
    result_payload = payload_by_type[evidence_type]

    async with session_factory() as session:
        session_id = await _create_session(session, f"tenant-persist-{evidence_type.value.lower()}")
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        saved = await svc.create(
            tenant_id=f"tenant-persist-{evidence_type.value.lower()}",
            session_id=UUID(session_id),
            evidence_type=evidence_type,
            status=EvidenceResultStatus.PASS,
            producer="hv-010-canary-producer",
            producer_version="1.0",
            result=result_payload,
        )
        await session.commit()

        record = await session.get(EvidenceResultRecord, str(saved.id))
        assert record is not None
        assert record.result_json is None
        assert record.result_ciphertext is not None
        assert record.result_key_id == "test-evidence-result-key"
        assert canary_value.encode() not in record.result_ciphertext

        fetched = await repo.get(saved.id, f"tenant-persist-{evidence_type.value.lower()}")
        assert fetched is not None
        assert fetched.result == result_payload


async def test_cross_tenant_get_returns_none() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-iso-a")
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        saved = await svc.create(
            tenant_id="tenant-iso-a",
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="1",
        )
        await session.commit()

        assert await repo.get(saved.id, "tenant-iso-b") is None
        assert await repo.get(saved.id, "tenant-iso-a") is not None


async def test_required_audit_failure_leaves_no_evidence_result_row() -> None:
    """Invariant 12 / EVD-3.3.5 proof, same shape as Foundation-006's
    test_no_session_row_is_left_behind_after_required_audit_failure: a
    required-audit failure must not leave the governed effect (the
    EvidenceResult row) durably persisted."""
    from core.audit.service import AuditPersistenceError

    class FailingAuditEventRepository:
        async def add(self, event, dedupe_key=None):
            raise RuntimeError("simulated audit database outage")

        async def get_by_dedupe_key(self, tenant_id, session_id, dedupe_key):
            return None

        async def list_for_session(self, session_id, tenant_id):
            return []

    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-audit-failure")
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo, AuditService(FailingAuditEventRepository()), SqlAlchemyEvidenceRepository(session)
        )

        with pytest.raises(AuditPersistenceError):
            await svc.create(
                tenant_id="tenant-audit-failure",
                session_id=UUID(session_id),
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="p",
                producer_version="1",
            )
        await session.rollback()

    async with session_factory() as verify_session:
        from sqlalchemy import select

        result = await verify_session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.tenant_id == "tenant-audit-failure"
            )
        )
        assert result.scalars().all() == []


async def test_supersede_against_real_postgres_creates_new_row_original_untouched() -> None:
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-supersede")
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        original = await svc.create(
            tenant_id="tenant-supersede",
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.INCONCLUSIVE,
            producer="p",
            producer_version="1",
        )
        await session.commit()

        superseding = await svc.supersede(
            evidence_result_id=original.id,
            tenant_id="tenant-supersede",
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="2",
            result={"similarity": 0.9},
            score=0.9,
        )
        await session.commit()

        original_record = await repo.get(original.id, "tenant-supersede")
        assert original_record is not None
        assert original_record.status == EvidenceResultStatus.INCONCLUSIVE
        assert original_record.supersedes_id is None

        superseding_record = await repo.get(superseding.id, "tenant-supersede")
        assert superseding_record is not None
        assert superseding_record.supersedes_id == original.id

        # DE-003 §11: superseding must flip the original out of the
        # effective set -- list_effective_for_session returns only the
        # new row, not both.
        effective = await repo.list_effective_for_session(UUID(session_id), "tenant-supersede")
        assert {r.id for r in effective} == {superseding.id}


async def test_one_effective_per_type_index_rejects_two_effective_rows_direct_insert() -> None:
    """Direct proof against real PostgreSQL that
    ix_evidence_results_one_effective_per_type is enforced at the database
    level: two independent, non-superseding rows of the same evidence_type
    for one session cannot both be is_effective=true (DE-003 §11 finding
    -- nothing previously prevented this)."""
    async with session_factory() as session:
        session_id = await _create_session(session, "tenant-effective-index-test")
        session.add(
            EvidenceResultRecord(
                id=str(uuid4()),
                tenant_id="tenant-effective-index-test",
                session_id=session_id,
                evidence_type="FACE_MATCH",
                schema_version="1.0",
                status="PASS",
                reason_codes_json=[],
                producer="p",
                producer_version="1",
                parent_evidence_result_ids_json=[],
                produced_at=datetime.now(UTC),
                persisted_at=datetime.now(UTC),
                integrity_reference="ref-1",
                is_effective=True,
            )
        )
        await session.flush()
        session.add(
            EvidenceResultRecord(
                id=str(uuid4()),
                tenant_id="tenant-effective-index-test",
                session_id=session_id,
                evidence_type="FACE_MATCH",
                schema_version="1.0",
                status="PASS",
                reason_codes_json=[],
                producer="p",
                producer_version="1",
                parent_evidence_result_ids_json=[],
                produced_at=datetime.now(UTC),
                persisted_at=datetime.now(UTC),
                integrity_reference="ref-2",
                is_effective=True,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
