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
from core.evidence_result.exceptions import InvalidEvidenceResultError
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
    """DOCUMENT_QUALITY, not FACE_MATCH -- this proves the plain-JSON
    round trip for a SENSITIVE (not HIGHLY_SENSITIVE) type generically;
    DOCUMENT_QUALITY shares that same tier without needing FACE_MATCH's
    own role-id contract (BD-001.5 H.2)."""
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
            evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"quality_score": 0.77},
            score=0.77,
        )
        await session.commit()

        record = await session.get(EvidenceResultRecord, str(saved.id))
        assert record is not None
        assert record.result_json == {"quality_score": 0.77}
        assert record.result_ciphertext is None

        fetched = await repo.get(saved.id, "tenant-persist-plain")
        assert fetched is not None
        assert fetched.result == {"quality_score": 0.77}


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
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
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
    FACE_EMBEDDING_REFERENCE."""
    assert classify(evidence_type) == DataClassification.HIGHLY_SENSITIVE

    canary_value = f"CANARY-IDENTITY-VALUE-{uuid4()}"
    # Each type's registered result schema (core.evidence_result.schemas)
    # requires different fields -- a generic payload would fail schema
    # validation before ever reaching the encryption boundary this test
    # targets, so the canary is embedded in whatever shape each type
    # actually requires.
    payload_by_type = {
        EvidenceResultType.OCR_EXTRACTION: {
            "raw": canary_value,
            "fields": {"surname": canary_value},
        },
        EvidenceResultType.DOCUMENT_FIELD_EXTRACTION: {
            "full_name": None,
            "surname": canary_value,
            "given_names": None,
            "date_of_birth": None,
            "sex": None,
            "document_number": None,
            "nationality": None,
            "expiry_date": None,
            "extensions": {},
            "conflicted_fields": [],
        },
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
    """DOCUMENT_QUALITY, not FACE_MATCH -- generic real-Postgres
    supersession behavior, no need for FACE_MATCH's own role-id
    contract (BD-001.5 H.2)."""
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
            evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
            status=EvidenceResultStatus.INCONCLUSIVE,
            producer="p",
            producer_version="1",
        )
        await session.commit()

        superseding = await svc.supersede(
            evidence_result_id=original.id,
            tenant_id="tenant-supersede",
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
            status=EvidenceResultStatus.PASS,
            producer="p",
            producer_version="2",
            result={"quality_score": 0.9},
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


async def test_reference_and_probe_biometric_stages_are_simultaneously_effective() -> None:
    """BD-001.4/BD-001.5 (Slice H): the concrete proof the taxonomy split
    exists for -- a single session holds all six role-qualified
    FACE_DETECTION/FACE_QUALITY/FACE_EMBEDDING types as simultaneously
    effective rows, something a single undifferentiated FACE_EMBEDDING
    (etc.) member could never represent under
    ix_evidence_results_one_effective_per_type's own
    (tenant_id, session_id, evidence_type) scope."""
    tenant_id = "tenant-h1-simultaneous-effectiveness"
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        payload_by_type = {
            EvidenceResultType.FACE_DETECTION_REFERENCE: {"detected": True, "face_count": 1},
            EvidenceResultType.FACE_DETECTION_PROBE: {"detected": True, "face_count": 1},
            EvidenceResultType.FACE_QUALITY_REFERENCE: {"quality_score": 0.8},
            EvidenceResultType.FACE_QUALITY_PROBE: {"quality_score": 0.9},
            EvidenceResultType.FACE_EMBEDDING_REFERENCE: {
                "embedding": [0.1, 0.2, 0.3],
                "embedding_dimensions": 3,
            },
            EvidenceResultType.FACE_EMBEDDING_PROBE: {
                "embedding": [0.4, 0.5, 0.6],
                "embedding_dimensions": 3,
            },
        }
        for evidence_type, payload in payload_by_type.items():
            await svc.create(
                tenant_id=tenant_id,
                session_id=UUID(session_id),
                evidence_type=evidence_type,
                status=EvidenceResultStatus.PASS,
                producer="face-provider",
                producer_version="1.0",
                result=payload,
            )
        await session.commit()

        effective = await repo.list_effective_for_session(UUID(session_id), tenant_id)
        assert {r.evidence_type for r in effective} == set(payload_by_type)


async def test_face_match_reference_id_not_in_parents_is_rejected_before_any_write() -> None:
    """BD-001.5 H.2, end-to-end: EvidenceResultService.create() itself
    rejects an invalid FACE_MATCH construction (reference id not among
    the supplied parents) before anything is persisted -- proving the
    boundary is real at the actual call site BiometricProcessor will
    use, not only at the unit level (tests/unit/test_evidence_result_schemas.py)."""
    tenant_id = "tenant-h2-provenance-rejection"
    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        key_provider = LocalAesGcmKeyProvider({"test-evidence-result-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-result-key")
        svc = EvidenceResultService(
            repo,
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

        reference_embedding = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": [0.1, 0.2, 0.3], "embedding_dimensions": 3},
        )
        probe_embedding = await svc.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
            status=EvidenceResultStatus.PASS,
            producer="face-provider",
            producer_version="1.0",
            result={"embedding": [0.4, 0.5, 0.6], "embedding_dimensions": 3},
        )
        await session.commit()

        with pytest.raises(InvalidEvidenceResultError):
            await svc.create(
                tenant_id=tenant_id,
                session_id=UUID(session_id),
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="face-provider",
                producer_version="1.0",
                result={
                    "similarity": 0.83,
                    # a real UUID, but NOT one of the two parents below --
                    # the reference id must be a genuine forgery attempt,
                    # not merely absent, to prove membership is checked
                    # against the real parent set, not merely non-empty
                    "reference_evidence_result_id": str(uuid4()),
                    "probe_evidence_result_id": str(probe_embedding.id),
                },
                parent_evidence_result_ids=(reference_embedding.id, probe_embedding.id),
            )

        effective = await repo.list_effective_for_session(UUID(session_id), tenant_id)
        assert EvidenceResultType.FACE_MATCH not in {r.evidence_type for r in effective}
