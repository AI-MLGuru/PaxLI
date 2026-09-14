"""DP-002 Phase 1: real Postgres + MinIO integration tests for
SqlAlchemyDocumentProcessor -- the orchestration boundary between a
DOCUMENT capture and typed, lineage-bearing DOCUMENT_QUALITY/
DOCUMENT_CLASSIFICATION EvidenceResult rows.

Tested here rather than as pure unit tests against fakes: like
infrastructure.deletion.reconciliation's reconciler classes (the same
"needs its own independent sessions" shape, same testing convention
throughout this codebase), SqlAlchemyDocumentProcessor constructs real
SqlAlchemy repositories internally against session_factory -- there is
no fake-repository seam to unit-test against, and the two deterministic
capabilities (core.document.deterministic) are already covered by pure
unit tests (tests/unit/test_document_deterministic.py).

Skipped when Postgres and/or MinIO aren't reachable, mirroring
tests/integration/test_evidence_submission_failure_injection.py.
"""

import asyncio
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome
from core.decision.orchestration import DecisionOrchestrator
from core.decision.persistence import DecisionPersistenceService
from core.document.capabilities import (
    BarcodeDecoder,
    CapabilityUnavailableError,
    DocumentClassifier,
    MRZParser,
    OCREngine,
    QualityAssessor,
)
from core.document.deterministic import (
    DeterministicBarcodeDecoder,
    DeterministicDocumentClassifier,
    DeterministicFieldReconciler,
    DeterministicMRZParser,
    DeterministicOCREngine,
    DeterministicQualityAssessor,
)
from core.document.reconciliation import DocumentFieldReconciler
from core.document.types import DocumentClassification, QualityAssessment
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence_result.enums import DocumentType, EvidenceResultStatus, EvidenceResultType
from core.evidence_result.schema_catalog import EvidenceResultSchemaCatalog
from core.evidence_result.service import EvidenceResultService
from core.policy.condition import EvidenceCondition
from core.policy.requirements import EvidenceRequirement, EvidenceRequirementLevel
from core.policy.rules import Rule
from core.policy.service import PolicyService
from core.verification.enums import AssuranceLevel
from core.verification.service import VerificationSessionService
from core.verification.workflow import VerificationWorkflowService
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.evidence_result import EvidenceResultRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.decision import SqlAlchemyDecisionRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
from infrastructure.database.repositories.policy import SqlAlchemyVerificationPolicyRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import session_factory
from infrastructure.document.processor import SqlAlchemyDocumentProcessor
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

# The canonical ICAO Doc 9303 Part 4 reference MRZ (Anna Maria Eriksson) --
# same vector as tests/unit/test_mrz.py, reproduced here so this file's
# integration tests don't depend on unit-test module internals.
_MRZ_LINE1 = "P<UTOERIKSSON<<ANNA<MARIA" + "<" * (44 - len("P<UTOERIKSSON<<ANNA<MARIA"))
_MRZ_LINE2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
_MRZ_VALID_RAW = _MRZ_LINE1 + _MRZ_LINE2


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


def _storage(key_id: str) -> EncryptedObjectStorage:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return EncryptedObjectStorage(MinioObjectStorage(get_settings()), key_provider, key_id)


async def _upload_document(
    session, tenant_id: str, session_id: str, storage, content: bytes
) -> UUID:
    """Direct EvidenceRecord + real storage.put() -- mirrors
    EvidenceService.add()'s own object_key convention without pulling in
    the full router/session-lifecycle machinery these tests don't need."""
    evidence_id = uuid4()
    checksum = f"doc-{uuid4()}"
    object_key = f"{tenant_id}/{session_id}/document/{checksum}"
    await storage.put(object_key, content, "image/jpeg")
    session.add(
        EvidenceRecord(
            id=str(evidence_id),
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=EvidenceType.DOCUMENT.value,
            source=EvidenceSource.CLIENT.value,
            object_key=object_key,
            checksum=checksum,
            mime_type="image/jpeg",
            size_bytes=len(content),
            metadata_json={},
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return evidence_id


def _processor(
    key_id: str,
    storage,
    quality_assessor: QualityAssessor | None = None,
    document_classifier: DocumentClassifier | None = None,
    mrz_parser: MRZParser | None = None,
    barcode_decoder: BarcodeDecoder | None = None,
    ocr_engine: OCREngine | None = None,
    field_reconciler: DocumentFieldReconciler | None = None,
) -> SqlAlchemyDocumentProcessor:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return SqlAlchemyDocumentProcessor(
        session_factory,
        key_provider,
        key_id,
        storage,
        quality_assessor or DeterministicQualityAssessor(),
        document_classifier or DeterministicDocumentClassifier(),
        mrz_parser or DeterministicMRZParser(),
        barcode_decoder or DeterministicBarcodeDecoder(),
        ocr_engine or DeterministicOCREngine(),
        field_reconciler or DeterministicFieldReconciler(),
    )


async def _effective_result(session, session_id: str, tenant_id: str, evidence_type: str):
    result = await session.execute(
        select(EvidenceResultRecord).where(
            EvidenceResultRecord.session_id == session_id,
            EvidenceResultRecord.tenant_id == tenant_id,
            EvidenceResultRecord.evidence_type == evidence_type,
            EvidenceResultRecord.is_effective.is_(True),
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Counting/failing capability doubles -- real classes, not mocks, matching
# this project's established failure-injection convention.
# ---------------------------------------------------------------------------


class _CountingQualityAssessor(QualityAssessor):
    def __init__(self, delegate: QualityAssessor) -> None:
        self.calls = 0
        self._delegate = delegate

    async def assess(self, image: bytes) -> QualityAssessment:
        self.calls += 1
        return await self._delegate.assess(image)


class _CountingDocumentClassifier(DocumentClassifier):
    def __init__(self, delegate: DocumentClassifier) -> None:
        self.calls = 0
        self._delegate = delegate

    async def classify(self, image: bytes) -> DocumentClassification:
        self.calls += 1
        return await self._delegate.classify(image)


class _UnavailableQualityAssessor(QualityAssessor):
    async def assess(self, image: bytes) -> QualityAssessment:
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


class _BuggyQualityAssessor(QualityAssessor):
    """Simulates a genuine programming defect -- NOT a known, self-
    diagnosed failure. DP-002's exception-taxonomy amendment requires
    this to propagate out of DocumentProcessor uncaught, never silently
    normalized into an ordinary UNAVAILABLE result."""

    async def assess(self, image: bytes) -> QualityAssessment:
        raise AttributeError("simulated programming defect, not a known capability failure")


class _CountingMRZParser(MRZParser):
    def __init__(self, delegate: MRZParser) -> None:
        self.calls = 0
        self._delegate = delegate

    async def parse(self, image: bytes):
        self.calls += 1
        return await self._delegate.parse(image)


class _CountingBarcodeDecoder(BarcodeDecoder):
    def __init__(self, delegate: BarcodeDecoder) -> None:
        self.calls = 0
        self._delegate = delegate

    async def decode(self, image: bytes):
        self.calls += 1
        return await self._delegate.decode(image)


class _UnavailableMRZParser(MRZParser):
    async def parse(self, image: bytes):
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


class _BuggyMRZParser(MRZParser):
    """HV-011: simulates a genuine programming defect in the real
    zone-detection/parsing pipeline -- NOT a known, self-diagnosed
    failure. Must propagate out of DocumentProcessor uncaught, exactly
    like _BuggyQualityAssessor already proves for Phase 1's capabilities."""

    async def parse(self, image: bytes):
        raise AttributeError("simulated programming defect, not a known capability failure")


class _BuggyBarcodeDecoder(BarcodeDecoder):
    async def decode(self, image: bytes):
        raise AttributeError("simulated programming defect, not a known capability failure")


class _UnavailableBarcodeDecoder(BarcodeDecoder):
    async def decode(self, image: bytes):
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


class _CountingOCREngine(OCREngine):
    def __init__(self, delegate: OCREngine) -> None:
        self.calls = 0
        self._delegate = delegate

    async def extract(self, image: bytes):
        self.calls += 1
        return await self._delegate.extract(image)


class _BuggyOCREngine(OCREngine):
    async def extract(self, image: bytes):
        raise AttributeError("simulated programming defect, not a known capability failure")


class _UnavailableOCREngine(OCREngine):
    async def extract(self, image: bytes):
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


class _CountingFieldReconciler(DocumentFieldReconciler):
    """Sync, unlike every _Counting* double above -- mirrors
    DocumentFieldReconciler's own contract (DP-009 §3), not
    core.document.capabilities'."""

    def __init__(self, delegate: DocumentFieldReconciler) -> None:
        self.calls = 0
        self._delegate = delegate

    def reconcile(self, *, ocr, mrz, barcode):
        self.calls += 1
        return self._delegate.reconcile(ocr=ocr, mrz=mrz, barcode=barcode)


class _BuggyFieldReconciler(DocumentFieldReconciler):
    def reconcile(self, *, ocr, mrz, barcode):
        raise AttributeError("simulated programming defect, not a known capability failure")


async def test_full_round_trip_produces_correct_quality_and_classification() -> None:
    tenant_id = f"tenant-docproc-happy-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value
        assert quality.source_reference == str(capture_id)
        assert quality.result_json == {"quality_score": 1.0}

        assert classification is not None
        assert classification.status == EvidenceResultStatus.PASS.value
        assert classification.source_reference == str(capture_id)
        assert classification.result_json == {"document_type": DocumentType.STANDARD_NIN_SLIP.value}


async def test_unrecognized_document_fails_classification_but_not_quality() -> None:
    """Partial-stage independence (DP-001 Decision 2/REL-10.15): an
    unrecognized document must not affect the independently-computed
    quality result."""
    tenant_id = f"tenant-docproc-unsupported-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"not a recognized document at all",
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value  # unaffected

        assert classification is not None
        assert classification.status == EvidenceResultStatus.FAIL.value
        assert classification.reason_codes_json == ["DOCUMENT_UNSUPPORTED"]
        assert classification.result_json is None


async def test_zero_captures_is_a_noop() -> None:
    tenant_id = f"tenant-docproc-none-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        assert await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY") is None
        assert (
            await _effective_result(session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION")
            is None
        )


async def test_ambiguous_captures_produce_inconclusive_without_invoking_any_capability() -> None:
    """DP-002 reconciliation amendment: more than one eligible DOCUMENT
    capture is an explicit precondition failure, checked BEFORE any
    capability runs -- never an implicit selection rule."""
    tenant_id = f"tenant-docproc-ambiguous-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES + b"0" * 2000 + b"one"
        )
        await _upload_document(
            session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES + b"0" * 2000 + b"two"
        )
        await session.commit()

    quality_assessor = _CountingQualityAssessor(DeterministicQualityAssessor())
    document_classifier = _CountingDocumentClassifier(DeterministicDocumentClassifier())
    mrz_parser = _CountingMRZParser(DeterministicMRZParser())
    barcode_decoder = _CountingBarcodeDecoder(DeterministicBarcodeDecoder())
    ocr_engine = _CountingOCREngine(DeterministicOCREngine())
    field_reconciler = _CountingFieldReconciler(DeterministicFieldReconciler())
    processor = _processor(
        key_id, storage, quality_assessor, document_classifier, mrz_parser, barcode_decoder,
        ocr_engine, field_reconciler,
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert quality_assessor.calls == 0  # precondition short-circuits before any capability runs
    assert document_classifier.calls == 0
    assert mrz_parser.calls == 0
    assert barcode_decoder.calls == 0
    assert ocr_engine.calls == 0
    assert field_reconciler.calls == 0

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        field_extraction = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
        )
        for result in (quality, classification, mrz, barcode, ocr, field_extraction):
            assert result is not None
            assert result.status == EvidenceResultStatus.INCONCLUSIVE.value
            assert result.reason_codes_json == ["AMBIGUOUS_DOCUMENT_CAPTURE"]
            assert result.source_reference is None  # no single capture to attribute to


async def test_wrong_tenant_id_sees_no_captures_and_never_touches_the_owning_tenant() -> None:
    """HV-010: list_for_session filters by (session_id, tenant_id) together,
    so a session_id belonging to one tenant, processed under a DIFFERENT
    tenant_id, must be indistinguishable from a genuinely empty session --
    never an implicit cross-tenant read of the real owner's document, and
    never an EvidenceResult row materializing under either tenant as a
    side effect. Attacks the boundary directly at the capability-
    invocation level (0 calls), not just the persisted-result level, since
    a leak that stopped short of persisting but still fed the wrong
    tenant's document bytes into a capability would still be a real
    breach."""
    owning_tenant = f"tenant-docproc-owner-{uuid4()}"
    attacking_tenant = f"tenant-docproc-attacker-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, owning_tenant)
        await _upload_document(
            session, owning_tenant, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    quality_assessor = _CountingQualityAssessor(DeterministicQualityAssessor())
    document_classifier = _CountingDocumentClassifier(DeterministicDocumentClassifier())
    mrz_parser = _CountingMRZParser(DeterministicMRZParser())
    barcode_decoder = _CountingBarcodeDecoder(DeterministicBarcodeDecoder())
    ocr_engine = _CountingOCREngine(DeterministicOCREngine())
    field_reconciler = _CountingFieldReconciler(DeterministicFieldReconciler())
    processor = _processor(
        key_id,
        storage,
        quality_assessor,
        document_classifier,
        mrz_parser,
        barcode_decoder,
        ocr_engine,
        field_reconciler,
    )
    # The attacker supplies the victim's real session_id but their OWN
    # tenant_id -- exactly the shape a tenant-scoping bug elsewhere in the
    # call chain (a forged header, a stale principal, a wiring mistake)
    # would produce by the time it reaches DocumentProcessor.
    await processor.process(session_id=UUID(session_id), tenant_id=attacking_tenant)

    assert quality_assessor.calls == 0
    assert document_classifier.calls == 0
    assert mrz_parser.calls == 0  # HV-011: attacked directly at the new stages too
    assert barcode_decoder.calls == 0
    assert ocr_engine.calls == 0  # HV-012: and at Phase 3's new stage too
    assert field_reconciler.calls == 0  # Phase 4: and at the sixth stage too

    async with session_factory() as session:
        for tenant_id in (owning_tenant, attacking_tenant):
            for evidence_type in (
                "DOCUMENT_QUALITY",
                "DOCUMENT_CLASSIFICATION",
                "MRZ",
                "BARCODE_QR",
                "OCR_EXTRACTION",
                "DOCUMENT_FIELD_EXTRACTION",
            ):
                result = await _effective_result(session, session_id, tenant_id, evidence_type)
                assert result is None

    # The real owner's document is still unprocessed and processes
    # correctly once addressed under its own tenant -- proving the prior
    # call didn't corrupt or consume it.
    await processor.process(session_id=UUID(session_id), tenant_id=owning_tenant)
    assert quality_assessor.calls == 1
    assert document_classifier.calls == 1
    assert mrz_parser.calls == 1
    assert barcode_decoder.calls == 1
    assert ocr_engine.calls == 1
    assert field_reconciler.calls == 1
    async with session_factory() as session:
        quality = await _effective_result(session, session_id, owning_tenant, "DOCUMENT_QUALITY")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value


async def test_concurrent_cross_tenant_processing_does_not_leak_or_corrupt() -> None:
    """HV-012 tenant-isolation category: the wrong-tenant test above proves
    the boundary holds for a single sequential attempt -- this attacks it
    under genuine concurrency, racing the real owner's legitimate
    process() call against an attacker's forged-tenant call for the same
    session_id at the same time. Neither call may observe or influence
    the other: the attacker must still see nothing, and the owner's
    result must still be correct and uncorrupted regardless of which
    call's transaction happens to interleave first."""
    owning_tenant = f"tenant-docproc-race-owner-{uuid4()}"
    attacking_tenant = f"tenant-docproc-race-attacker-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, owning_tenant)
        capture_id = await _upload_document(
            session, owning_tenant, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    processor_owner = _processor(key_id, storage)
    processor_attacker = _processor(key_id, storage)

    await asyncio.gather(
        processor_owner.process(session_id=UUID(session_id), tenant_id=owning_tenant),
        processor_attacker.process(session_id=UUID(session_id), tenant_id=attacking_tenant),
    )

    async with session_factory() as session:
        for evidence_type in (
            "DOCUMENT_QUALITY",
            "DOCUMENT_CLASSIFICATION",
            "MRZ",
            "BARCODE_QR",
            "OCR_EXTRACTION",
            "DOCUMENT_FIELD_EXTRACTION",
        ):
            assert (
                await _effective_result(session, session_id, attacking_tenant, evidence_type)
                is None
            )

        ocr = await _effective_result(session, session_id, owning_tenant, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.PASS.value
        assert ocr.source_reference == str(capture_id)

        field_extraction = await _effective_result(
            session, session_id, owning_tenant, "DOCUMENT_FIELD_EXTRACTION"
        )
        assert field_extraction is not None
        assert field_extraction.status == EvidenceResultStatus.PASS.value

        # Exactly one effective row overall for each -- the attacker's
        # concurrent forged-tenant call never raced its way into creating
        # or corrupting the owner's rows.
        for evidence_type in ("OCR_EXTRACTION", "DOCUMENT_FIELD_EXTRACTION"):
            result = await session.execute(
                select(EvidenceResultRecord).where(
                    EvidenceResultRecord.session_id == session_id,
                    EvidenceResultRecord.evidence_type == evidence_type,
                    EvidenceResultRecord.is_effective.is_(True),
                )
            )
            assert len(result.scalars().all()) == 1


async def test_concurrent_process_calls_converge_on_one_effective_result_per_type() -> None:
    """HV-010: two concurrent process() calls for the same session (the
    real-world shape of a client double-submitting, or WF-006's GET-
    triggered PROCESSING recovery racing a still-in-flight /submit) must
    not both reach create() for the same (session_id, evidence_type) --
    the partial unique index on is_effective is the final backstop, but a
    raw IntegrityError surfacing out of DocumentProcessor.process() would
    still be a real defect this test rules out directly, mirroring
    test_submit_api_wiring.py's own concurrent-convergence proof one layer
    up."""
    tenant_id = f"tenant-docproc-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    processor_a = _processor(key_id, storage)
    processor_b = _processor(key_id, storage)

    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    async with session_factory() as session:
        for evidence_type in ("DOCUMENT_QUALITY", "DOCUMENT_CLASSIFICATION"):
            effective_rows = await session.execute(
                select(EvidenceResultRecord).where(
                    EvidenceResultRecord.session_id == session_id,
                    EvidenceResultRecord.evidence_type == evidence_type,
                    EvidenceResultRecord.is_effective.is_(True),
                )
            )
            rows = effective_rows.scalars().all()
            assert len(rows) == 1, (
                f"{evidence_type}: expected exactly one effective row, got {len(rows)}"
            )
            assert rows[0].status == EvidenceResultStatus.PASS.value
            assert rows[0].source_reference == str(capture_id)

        # HV-012: this fixture carries no OCR marker, so OCR converges on
        # UNREADABLE rather than PASS -- still exactly one effective row.
        ocr_rows = (
            await session.execute(
                select(EvidenceResultRecord).where(
                    EvidenceResultRecord.session_id == session_id,
                    EvidenceResultRecord.evidence_type == "OCR_EXTRACTION",
                    EvidenceResultRecord.is_effective.is_(True),
                )
            )
        ).scalars().all()
        assert len(ocr_rows) == 1, (
            f"OCR_EXTRACTION: expected exactly one effective row, got {len(ocr_rows)}"
        )
        assert ocr_rows[0].status == EvidenceResultStatus.INCONCLUSIVE.value
        assert ocr_rows[0].source_reference == str(capture_id)

        # Phase 4: every source is absent for this fixture (no OCR/MRZ/
        # Barcode marker), so reconciliation finds nothing to disagree
        # about -- PASS with no conflicted_fields, still exactly one
        # effective row despite the concurrent race.
        field_extraction_rows = (
            await session.execute(
                select(EvidenceResultRecord).where(
                    EvidenceResultRecord.session_id == session_id,
                    EvidenceResultRecord.evidence_type == "DOCUMENT_FIELD_EXTRACTION",
                    EvidenceResultRecord.is_effective.is_(True),
                )
            )
        ).scalars().all()
        assert len(field_extraction_rows) == 1, (
            f"DOCUMENT_FIELD_EXTRACTION: expected exactly one effective row, "
            f"got {len(field_extraction_rows)}"
        )
        assert field_extraction_rows[0].status == EvidenceResultStatus.PASS.value


async def _effective_row_count(session_id: str, evidence_type: str) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id,
                EvidenceResultRecord.evidence_type == evidence_type,
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        return len(result.scalars().all())


async def test_concurrent_mrz_processing_converges_on_one_effective_result() -> None:
    """HV-011: HV-010's concurrent-create fix (EffectiveResultAlreadyExistsError)
    is generic across EvidenceResultType, but inheritance is NOT assumed
    here -- attacked directly at MRZ's own call site with a real VALID
    marker (exercising the full real check-digit-validation path under
    the race, not just the cheap NOT_SUBMITTED path the general Phase 1
    concurrency test happens to exercise for this type)."""
    tenant_id = f"tenant-docproc-mrz-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE" + marker,
        )
        await session.commit()

    processor_a = _processor(key_id, storage)
    processor_b = _processor(key_id, storage)

    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    assert await _effective_row_count(session_id, "MRZ") == 1
    async with session_factory() as session:
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.PASS.value
        assert mrz.source_reference == str(capture_id)


async def test_concurrent_barcode_processing_converges_on_one_effective_result() -> None:
    """HV-011: same attack, at BarcodeDecoder's own call site."""
    tenant_id = f"tenant-docproc-barcode-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_BARCODE_VALID:PDF417:document_number=A1234567\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    processor_a = _processor(key_id, storage)
    processor_b = _processor(key_id, storage)

    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    assert await _effective_row_count(session_id, "BARCODE_QR") == 1
    async with session_factory() as session:
        barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
        assert barcode is not None
        assert barcode.status == EvidenceResultStatus.PASS.value
        assert barcode.source_reference == str(capture_id)


async def test_concurrent_ocr_processing_converges_on_one_effective_result() -> None:
    """HV-012: same attack, at OCREngine's own call site."""
    tenant_id = f"tenant-docproc-ocr-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    processor_a = _processor(key_id, storage)
    processor_b = _processor(key_id, storage)

    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    assert await _effective_row_count(session_id, "OCR_EXTRACTION") == 1
    async with session_factory() as session:
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.PASS.value
        assert ocr.source_reference == str(capture_id)


async def test_concurrent_field_extraction_converges_on_one_effective_result() -> None:
    """DP-009 §9: the same race, at DocumentFieldReconciler's own call
    site -- the sixth stage, and the first whose reuse eligibility
    depends on more than its own row's status (DP-008 §4's freshness
    principle), is not assumed to inherit the general concurrent-create
    fix without direct proof."""
    tenant_id = f"tenant-docproc-field-extraction-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    processor_a = _processor(key_id, storage)
    processor_b = _processor(key_id, storage)

    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    assert await _effective_row_count(session_id, "DOCUMENT_FIELD_EXTRACTION") == 1
    async with session_factory() as session:
        field_extraction = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
        )
        assert field_extraction is not None
        assert field_extraction.status == EvidenceResultStatus.PASS.value


async def test_concurrent_processing_of_different_captures_does_not_interfere() -> None:
    """HV-011: a fix that eliminated the concurrent-create race by
    serializing ALL document processing globally would technically pass
    the two tests above while introducing an unacceptable throughput
    regression -- ruled out directly by processing two genuinely
    different sessions/captures/tenants concurrently and confirming both
    converge to their own correct, independent result. The
    EffectiveResultAlreadyExistsError fix is a SAVEPOINT scoped to one
    row's own insert attempt (infrastructure/database/repositories/
    evidence_result.py), never a table- or session-wide lock -- this is
    the functional proof that holds regardless of the underlying
    mechanism."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async def _create_and_process(marker_suffix: bytes) -> tuple[str, UUID]:
        tenant_id = f"tenant-docproc-crosscapture-{uuid4()}"
        async with session_factory() as session:
            session_id = await _create_session(session, tenant_id)
            capture_id = await _upload_document(
                session, tenant_id, session_id, storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000
                + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE" + marker_suffix,
            )
            await session.commit()
        processor = _processor(key_id, storage)
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
        return session_id, capture_id

    marker_a = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")
    corrupted_line2 = _MRZ_LINE2[:9] + "5" + _MRZ_LINE2[10:]
    marker_b = b"PAXLI_TEST_MRZ:" + (_MRZ_LINE1 + corrupted_line2).encode("ascii")

    (session_id_a, capture_a), (session_id_b, capture_b) = await asyncio.gather(
        _create_and_process(marker_a), _create_and_process(marker_b)
    )

    async with session_factory() as session:
        mrz_a = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id_a,
                EvidenceResultRecord.evidence_type == "MRZ",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        row_a = mrz_a.scalar_one()
        assert row_a.status == EvidenceResultStatus.PASS.value
        assert row_a.source_reference == str(capture_a)

        mrz_b = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id_b,
                EvidenceResultRecord.evidence_type == "MRZ",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        row_b = mrz_b.scalar_one()
        assert row_b.status == EvidenceResultStatus.FAIL.value
        assert row_b.source_reference == str(capture_b)


async def test_concurrent_ocr_processing_of_different_captures_does_not_interfere() -> None:
    """HV-012: the same cross-capture non-interference proof as above,
    attacked directly at OCR's own call site with two DISTINCT valid OCR
    payloads processed concurrently -- ruling out the specific OCR risk
    that the module-level marker-extraction helpers could somehow mix up
    which image's bytes produced which raw text under a race, not just
    that the two effective rows stay separate."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async def _create_and_process(ocr_text: str) -> tuple[str, str, UUID]:
        tenant_id = f"tenant-docproc-ocr-crosscapture-{uuid4()}"
        marker = f"PAXLI_TEST_OCR_VALID:{ocr_text}\x00".encode()
        async with session_factory() as session:
            session_id = await _create_session(session, tenant_id)
            capture_id = await _upload_document(
                session, tenant_id, session_id, storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
            )
            await session.commit()
        processor = _processor(key_id, storage)
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
        return tenant_id, session_id, capture_id

    (tenant_a, session_id_a, capture_a), (tenant_b, session_id_b, capture_b) = (
        await asyncio.gather(
            _create_and_process("surname=FIRST_CAPTURE_ANNA"),
            _create_and_process("surname=SECOND_CAPTURE_MULLER"),
        )
    )

    async with session_factory() as session:
        ocr_a = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id_a,
                EvidenceResultRecord.evidence_type == "OCR_EXTRACTION",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        row_a = ocr_a.scalar_one()
        assert row_a.status == EvidenceResultStatus.PASS.value
        assert row_a.source_reference == str(capture_a)

        ocr_b = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id_b,
                EvidenceResultRecord.evidence_type == "OCR_EXTRACTION",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        row_b = ocr_b.scalar_one()
        assert row_b.status == EvidenceResultStatus.PASS.value
        assert row_b.source_reference == str(capture_b)

    # The raw OCR text itself -- not just the row's status/lineage --
    # must not have been swapped between the two concurrent captures.
    # Decrypt via the same service path the API uses, since raw text
    # lives in result_ciphertext (OCR_EXTRACTION is HIGHLY_SENSITIVE).
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    async with session_factory() as session:
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        result_a = await evidence_result_service.get_effective_for_session_by_type(
            session_id=UUID(session_id_a),
            tenant_id=tenant_a,
            evidence_type=EvidenceResultType.OCR_EXTRACTION,
        )
        result_b = await evidence_result_service.get_effective_for_session_by_type(
            session_id=UUID(session_id_b),
            tenant_id=tenant_b,
            evidence_type=EvidenceResultType.OCR_EXTRACTION,
        )
        assert result_a is not None and result_a.result is not None
        assert result_b is not None and result_b.result is not None
        assert result_a.result["fields"] == {"surname": "FIRST_CAPTURE_ANNA"}
        assert result_b.result["fields"] == {"surname": "SECOND_CAPTURE_MULLER"}


async def test_retry_does_not_recompute_an_already_reusable_result() -> None:
    tenant_id = f"tenant-docproc-convergence-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE",
        )
        await session.commit()

    quality_assessor = _CountingQualityAssessor(DeterministicQualityAssessor())
    document_classifier = _CountingDocumentClassifier(DeterministicDocumentClassifier())
    mrz_parser = _CountingMRZParser(DeterministicMRZParser())
    barcode_decoder = _CountingBarcodeDecoder(DeterministicBarcodeDecoder())
    ocr_engine = _CountingOCREngine(DeterministicOCREngine())
    processor = _processor(
        key_id,
        storage,
        quality_assessor,
        document_classifier,
        mrz_parser,
        barcode_decoder,
        ocr_engine,
    )

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert quality_assessor.calls == 1
    assert document_classifier.calls == 1
    assert mrz_parser.calls == 1
    assert barcode_decoder.calls == 1
    assert ocr_engine.calls == 1

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert quality_assessor.calls == 1  # NOT recomputed -- PASS is terminal/reusable
    assert document_classifier.calls == 1
    # No MRZ/barcode/OCR marker on this fixture -> NOT_SUBMITTED/UNREADABLE
    # -- DP-003 Decision 9's terminal/reusable claim confirmed directly,
    # not assumed.
    assert mrz_parser.calls == 1
    assert barcode_decoder.calls == 1
    assert ocr_engine.calls == 1


async def test_mrz_pass_result_is_not_recomputed_on_retry() -> None:
    """DP-003 Decision 9 for the VALID/PASS branch specifically -- the
    prior test proves NOT_SUBMITTED's reusability; this proves a real
    successful MRZ read is equally terminal, not just the absence case."""
    tenant_id = f"tenant-docproc-mrz-convergence-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        marker = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE" + marker,
        )
        await session.commit()

    mrz_parser = _CountingMRZParser(DeterministicMRZParser())
    processor = _processor(key_id, storage, mrz_parser=mrz_parser)

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert mrz_parser.calls == 1
    async with session_factory() as session:
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.PASS.value

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert mrz_parser.calls == 1  # NOT recomputed


async def test_ocr_valid_result_is_not_recomputed_on_retry() -> None:
    """DP-005 Decision 9 for the VALID branch specifically -- mirrors
    test_mrz_pass_result_is_not_recomputed_on_retry exactly, confirming
    OCR's terminal/reusable behavior is proven directly rather than
    assumed inherited from MRZ/Barcode's own proofs."""
    tenant_id = f"tenant-docproc-ocr-convergence-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    ocr_engine = _CountingOCREngine(DeterministicOCREngine())
    processor = _processor(key_id, storage, ocr_engine=ocr_engine)

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert ocr_engine.calls == 1
    async with session_factory() as session:
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.PASS.value

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert ocr_engine.calls == 1  # NOT recomputed


async def test_field_extraction_is_not_recomputed_when_parent_set_is_unchanged() -> None:
    """DP-008 §4's freshness principle, the reuse half: when none of the
    three parent rows change between attempts, the derived result is
    reused exactly like every independent stage's own terminal result
    is -- confirmed directly, not merely assumed from the freshness
    test's recompute half."""
    tenant_id = f"tenant-docproc-field-extraction-reuse-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    field_reconciler = _CountingFieldReconciler(DeterministicFieldReconciler())
    processor = _processor(key_id, storage, field_reconciler=field_reconciler)

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert field_reconciler.calls == 1
    async with session_factory() as session:
        first = await _effective_result(session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION")
        assert first is not None
        first_id = first.id

    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert field_reconciler.calls == 1  # NOT recomputed -- no parent changed
    async with session_factory() as session:
        second = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
        )
        assert second is not None
        assert second.id == first_id  # the exact same row, not a new one


async def test_field_extraction_is_recomputed_when_a_parent_is_superseded() -> None:
    """DP-008 §4's freshness principle, the recompute half -- the test
    that proves the principle is actually implemented, not just
    described. Round 1: OCR is UNAVAILABLE (a real capability outage),
    so the first reconciliation is built with ocr=None. Round 2: OCR
    retries successfully, superseding its own row -- MRZ/Barcode's rows
    stay exactly the same (already terminal, reused). The derived
    result's stored parent set (ocr_v1, mrz, barcode) no longer matches
    the CURRENT effective parent set (ocr_v2, mrz, barcode), so it MUST
    be recomputed, not silently reused despite its own status looking
    terminal (PASS, with no conflicted_fields, from round 1's
    all-ABSENT/INSUFFICIENT result)."""
    tenant_id = f"tenant-docproc-field-extraction-freshness-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    field_reconciler = _CountingFieldReconciler(DeterministicFieldReconciler())
    failing_ocr_processor = _processor(
        key_id, storage, ocr_engine=_UnavailableOCREngine(), field_reconciler=field_reconciler
    )
    await failing_ocr_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert field_reconciler.calls == 1

    async with session_factory() as session:
        ocr_v1 = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr_v1 is not None
        assert ocr_v1.status == EvidenceResultStatus.UNAVAILABLE.value
        first = await _effective_result(session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION")
        assert first is not None
        assert first.status == EvidenceResultStatus.PASS.value  # nothing to disagree about yet
        first_id = first.id

    # A real retry: OCR now succeeds, carrying real data none of the
    # (still-absent) other sources can conflict with. Overwrites the
    # SAME capture's stored bytes in place -- _run_ocr re-reads storage
    # fresh on every process() call, so this is enough to change what
    # the retry actually sees, without needing a second capture.
    marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"
    async with session_factory() as session:
        object_key = await session.scalar(
            select(EvidenceRecord.object_key).where(EvidenceRecord.session_id == session_id)
        )
    assert object_key is not None
    await storage.put(
        object_key,
        MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP" + marker,
        "image/jpeg",
    )
    working_processor = _processor(key_id, storage, field_reconciler=field_reconciler)
    await working_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        ocr_v2 = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr_v2 is not None
        assert ocr_v2.status == EvidenceResultStatus.PASS.value
        assert ocr_v2.id != ocr_v1.id  # OCR itself was superseded

        current_mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        current_barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
        assert current_mrz is not None and current_barcode is not None

        second = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
        )
        assert second is not None
        assert second.id != first_id  # recomputed, not reused
        assert second.supersedes_id == first_id
        assert set(second.parent_evidence_result_ids_json) == {
            str(ocr_v2.id),
            str(current_mrz.id),
            str(current_barcode.id),
        }
    assert field_reconciler.calls == 2  # actually recomputed, not reused


async def test_capability_unavailable_error_produces_unavailable_result_and_is_retryable() -> None:
    tenant_id = f"tenant-docproc-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    failing_processor = _processor(key_id, storage, quality_assessor=_UnavailableQualityAssessor())
    await failing_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.UNAVAILABLE.value
        assert quality.reason_codes_json == ["MODEL_UNAVAILABLE"]
        first_attempt_id = quality.id

    # A real retry (a working capability this time) MUST supersede the
    # prior UNAVAILABLE attempt, not create a second effective result.
    working_processor = _processor(key_id, storage)
    await working_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value
        assert quality.id != first_attempt_id
        assert quality.supersedes_id == first_attempt_id

        # Exactly one effective DOCUMENT_QUALITY row -- the partial unique
        # index's own guarantee, confirmed directly.
        result = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id,
                EvidenceResultRecord.evidence_type == "DOCUMENT_QUALITY",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        assert len(result.scalars().all()) == 1


async def test_mrz_unavailable_result_is_retryable_and_superseded_by_real_attempt() -> None:
    tenant_id = f"tenant-docproc-mrz-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        marker = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE" + marker,
        )
        await session.commit()

    failing_processor = _processor(key_id, storage, mrz_parser=_UnavailableMRZParser())
    await failing_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.UNAVAILABLE.value
        assert mrz.reason_codes_json == ["MODEL_UNAVAILABLE"]
        first_attempt_id = mrz.id

    working_processor = _processor(key_id, storage)
    await working_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.PASS.value
        assert mrz.id != first_attempt_id
        assert mrz.supersedes_id == first_attempt_id

        result = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id,
                EvidenceResultRecord.evidence_type == "MRZ",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        assert len(result.scalars().all()) == 1


async def test_ocr_unavailable_result_is_retryable_and_superseded_by_real_attempt() -> None:
    """Mirrors test_mrz_unavailable_result_is_retryable_and_superseded_by_
    real_attempt exactly, for OCREngine's own UNAVAILABLE/retry path."""
    tenant_id = f"tenant-docproc-ocr-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    failing_processor = _processor(key_id, storage, ocr_engine=_UnavailableOCREngine())
    await failing_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.UNAVAILABLE.value
        assert ocr.reason_codes_json == ["MODEL_UNAVAILABLE"]
        first_attempt_id = ocr.id

    working_processor = _processor(key_id, storage)
    await working_processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.PASS.value
        assert ocr.id != first_attempt_id
        assert ocr.supersedes_id == first_attempt_id

        result = await session.execute(
            select(EvidenceResultRecord).where(
                EvidenceResultRecord.session_id == session_id,
                EvidenceResultRecord.evidence_type == "OCR_EXTRACTION",
                EvidenceResultRecord.is_effective.is_(True),
            )
        )
        assert len(result.scalars().all()) == 1


async def test_mrz_full_round_trip_covers_every_outcome_state() -> None:
    """DP-003 §7's frozen MRZ mapping, proven end to end for every state
    except UNAVAILABLE (covered separately above, since it needs a
    failing capability double rather than a marker) and NOT_SUBMITTED
    (already covered by test_retry_does_not_recompute_an_already_
    reusable_result's no-marker fixture)."""
    corrupted_line2 = _MRZ_LINE2[:9] + "5" + _MRZ_LINE2[10:]  # doc-number check digit was 6

    cases = (
        ("PAXLI_TEST_MRZ_UNREADABLE", EvidenceResultStatus.INCONCLUSIVE, "MRZ_UNREADABLE", False),
        (
            "PAXLI_TEST_MRZ:not a valid mrz structure at all" + "0" * 20,
            EvidenceResultStatus.INCONCLUSIVE,
            "MRZ_MALFORMED",
            True,
        ),
        (
            "PAXLI_TEST_MRZ:" + _MRZ_LINE1 + corrupted_line2,
            EvidenceResultStatus.FAIL,
            "MRZ_CHECK_DIGIT_MISMATCH",
            True,
        ),
        ("PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW, EvidenceResultStatus.PASS, None, True),
    )

    for marker_text, expected_status, expected_reason, expect_result in cases:
        tenant_id = f"tenant-docproc-mrz-outcome-{uuid4()}"
        key_id = f"key-{uuid4()}"
        storage = _storage(key_id)

        async with session_factory() as session:
            session_id = await _create_session(session, tenant_id)
            capture_id = await _upload_document(
                session, tenant_id, session_id, storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + marker_text.encode("ascii"),
            )
            await session.commit()

        processor = _processor(key_id, storage)
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

        async with session_factory() as session:
            mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
            assert mrz is not None, f"case {marker_text!r}: no MRZ result persisted"
            assert mrz.status == expected_status.value, f"case {marker_text!r}"
            assert mrz.source_reference == str(capture_id)
            if expected_reason:
                assert mrz.reason_codes_json == [expected_reason], f"case {marker_text!r}"
            else:
                assert mrz.reason_codes_json == [], f"case {marker_text!r}"
            # MRZ is HIGHLY_SENSITIVE (DP-001 Decision 1) -- a populated
            # result is encrypted, never plaintext result_json.
            assert mrz.result_json is None, f"case {marker_text!r}"
            if expect_result:
                assert mrz.result_ciphertext is not None, f"case {marker_text!r}"
            else:
                assert mrz.result_ciphertext is None, f"case {marker_text!r}"


async def test_barcode_full_round_trip_covers_every_outcome_state() -> None:
    """DP-003 §7's frozen Barcode/QR mapping, proven end to end for
    every state -- explicitly confirming FAIL is never among them."""
    cases = (
        ("PAXLI_TEST_BARCODE_UNREADABLE", EvidenceResultStatus.INCONCLUSIVE, "BARCODE_UNREADABLE"),
        (
            "PAXLI_TEST_BARCODE_UNRECOGNIZED:QR_CODE:opaque-token\x00",
            EvidenceResultStatus.INCONCLUSIVE,
            "BARCODE_PAYLOAD_UNRECOGNIZED",
        ),
        (
            "PAXLI_TEST_BARCODE_MALFORMED:PDF417:document_number=\x00",
            EvidenceResultStatus.INCONCLUSIVE,
            "BARCODE_PAYLOAD_MALFORMED",
        ),
        (
            "PAXLI_TEST_BARCODE_VALID:PDF417:document_number=A1234567\x00",
            EvidenceResultStatus.PASS,
            None,
        ),
    )

    for marker_text, expected_status, expected_reason in cases:
        tenant_id = f"tenant-docproc-barcode-outcome-{uuid4()}"
        key_id = f"key-{uuid4()}"
        storage = _storage(key_id)

        async with session_factory() as session:
            session_id = await _create_session(session, tenant_id)
            capture_id = await _upload_document(
                session, tenant_id, session_id, storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + marker_text.encode("ascii"),
            )
            await session.commit()

        processor = _processor(key_id, storage)
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

        async with session_factory() as session:
            barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
            assert barcode is not None, f"case {marker_text!r}: no BARCODE_QR result persisted"
            assert barcode.status == expected_status.value, f"case {marker_text!r}"
            assert barcode.status != EvidenceResultStatus.FAIL.value
            assert barcode.source_reference == str(capture_id)
            if expected_reason:
                assert barcode.reason_codes_json == [expected_reason], f"case {marker_text!r}"


async def test_ocr_full_round_trip_covers_every_outcome_state() -> None:
    """DP-005 §7's frozen OCR mapping, proven end to end for both states
    (UNREADABLE and VALID) -- explicitly confirming FAIL is never among
    them (DP-005 Decision 2: OCR has no standards-defined negative
    condition). OCR_EXTRACTION is HIGHLY_SENSITIVE (DP-005 Decision 7 /
    DP-001 Decision 1), so a populated result must be encrypted, never
    plaintext result_json -- mirrors test_mrz_full_round_trip_covers_
    every_outcome_state's encryption-boundary proof."""
    cases = (
        ("PAXLI_TEST_OCR_UNREADABLE", EvidenceResultStatus.INCONCLUSIVE, "OCR_UNREADABLE", False),
        (
            "PAXLI_TEST_OCR_VALID:surname=ERIKSSON;given_names=ANNA MARIA\x00",
            EvidenceResultStatus.PASS,
            None,
            True,
        ),
    )

    for marker_text, expected_status, expected_reason, expect_result in cases:
        tenant_id = f"tenant-docproc-ocr-outcome-{uuid4()}"
        key_id = f"key-{uuid4()}"
        storage = _storage(key_id)

        async with session_factory() as session:
            session_id = await _create_session(session, tenant_id)
            capture_id = await _upload_document(
                session, tenant_id, session_id, storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + marker_text.encode("utf-8"),
            )
            await session.commit()

        processor = _processor(key_id, storage)
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

        async with session_factory() as session:
            ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
            assert ocr is not None, f"case {marker_text!r}: no OCR_EXTRACTION result persisted"
            assert ocr.status == expected_status.value, f"case {marker_text!r}"
            assert ocr.status != EvidenceResultStatus.FAIL.value
            assert ocr.source_reference == str(capture_id)
            if expected_reason:
                assert ocr.reason_codes_json == [expected_reason], f"case {marker_text!r}"
            else:
                assert ocr.reason_codes_json == [], f"case {marker_text!r}"
            assert ocr.result_json is None, f"case {marker_text!r}"
            if expect_result:
                assert ocr.result_ciphertext is not None, f"case {marker_text!r}"
            else:
                assert ocr.result_ciphertext is None, f"case {marker_text!r}"


async def test_field_extraction_full_round_trip_covers_pass_and_inconclusive_outcomes() -> None:
    """DP-009 §5's frozen status logic (exactly two branches, no
    _FIELD_EXTRACTION_OUTCOME_MAP): PASS when conflicted_fields is
    empty, INCONCLUSIVE + FIELD_VALUE_CONFLICT when it isn't --
    explicitly confirming FAIL is never among them (no code path
    produces it). DOCUMENT_FIELD_EXTRACTION is HIGHLY_SENSITIVE (DP-001
    Decision 1, unchanged), so a populated result must be encrypted,
    never plaintext -- mirrors OCR/MRZ's own encryption-boundary proof.
    Also confirms parent_evidence_result_ids references exactly the
    three sibling rows."""
    # _MRZ_VALID_RAW's own real ICAO-parsed surname is always ERIKSSON
    # (the canonical reference vector) -- only OCR's surname varies here.
    cases = (
        ("ERIKSSON", EvidenceResultStatus.PASS, False),  # agrees with MRZ
        ("MULLER", EvidenceResultStatus.INCONCLUSIVE, True),  # disagrees with MRZ
    )

    for ocr_surname, expected_status, expect_conflict in cases:
        tenant_id = f"tenant-docproc-field-extraction-outcome-{uuid4()}"
        key_id = f"key-{uuid4()}"
        storage = _storage(key_id)
        ocr_marker = f"PAXLI_TEST_OCR_VALID:surname={ocr_surname}\x00".encode()
        mrz_marker = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")

        async with session_factory() as session:
            session_id = await _create_session(session, tenant_id)
            await _upload_document(
                session, tenant_id, session_id, storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE"
                + mrz_marker + ocr_marker,
            )
            await session.commit()

        processor = _processor(key_id, storage)
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

        async with session_factory() as session:
            ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
            mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
            barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
            assert ocr is not None and mrz is not None and barcode is not None

            field_extraction = await _effective_result(
                session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
            )
            assert field_extraction is not None, f"case ocr_surname={ocr_surname!r}"
            assert field_extraction.status == expected_status.value, (
                f"case ocr_surname={ocr_surname!r}"
            )
            assert field_extraction.status != EvidenceResultStatus.FAIL.value
            assert field_extraction.source_reference is None  # never examines the capture directly
            if expect_conflict:
                assert field_extraction.reason_codes_json == ["FIELD_VALUE_CONFLICT"]
            else:
                assert field_extraction.reason_codes_json == []
            # HIGHLY_SENSITIVE -- a populated result is always encrypted.
            assert field_extraction.result_json is None
            assert field_extraction.result_ciphertext is not None
            assert set(field_extraction.parent_evidence_result_ids_json) == {
                str(ocr.id), str(mrz.id), str(barcode.id),
            }


async def test_mrz_check_digit_mismatch_does_not_affect_quality_or_classification() -> None:
    """Partial-stage independence (REL-10.15), extended from Phase 1's
    unrecognized-document test to a Phase 2 stage -- and, per HV-011/
    HV-012/DP-009, to ALL SIX stages simultaneously with genuinely mixed
    outcomes (MRZ FAIL, Barcode PASS, OCR PASS, Quality/Classification
    PASS, DOCUMENT_FIELD_EXTRACTION PASS), not just a two-stage
    snapshot. Also exercises DP-009 §7.1 for real, not just at the unit
    level: MRZ's checksum-failed row still carries a real ICAO-parsed
    surname (ERIKSSON), which the reconciler treats as a genuine
    observation agreeing with OCR's -- MRZ's own FAIL status neither
    blocks nor gets overridden by that agreement."""
    tenant_id = f"tenant-docproc-mrz-partial-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    corrupted_line2 = _MRZ_LINE2[:9] + "5" + _MRZ_LINE2[10:]
    mrz_marker = b"PAXLI_TEST_MRZ:" + (_MRZ_LINE1 + corrupted_line2).encode("ascii")
    # document_number matches MRZ's own real ICAO-parsed value
    # (_MRZ_LINE2[0:9] = "L898902C3") deliberately -- an arbitrary
    # fixture value here would introduce an UNINTENDED second conflict
    # (found by actually running this test against the real reconciler,
    # not assumed away), muddying this test's one intended signal
    # (surname agreement despite MRZ's own FAIL).
    barcode_marker = b"PAXLI_TEST_BARCODE_VALID:PDF417:document_number=L898902C3\x00"
    ocr_marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE"
            + mrz_marker + barcode_marker + ocr_marker,
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        field_extraction = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
        )
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value  # unaffected
        assert classification is not None
        assert classification.status == EvidenceResultStatus.PASS.value  # unaffected
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.FAIL.value
        assert barcode is not None
        assert barcode.status == EvidenceResultStatus.PASS.value  # unaffected by MRZ's failure
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.PASS.value  # unaffected by MRZ's failure
        assert field_extraction is not None
        # DP-009 §7.1: MRZ's FAIL status doesn't block its data from
        # reconciliation -- OCR and MRZ both observed surname=ERIKSSON,
        # so reconciliation still agrees and PASSes, unaffected by MRZ's
        # own FAIL.
        assert field_extraction.status == EvidenceResultStatus.PASS.value
        assert field_extraction.reason_codes_json == []


async def test_ocr_unreadable_does_not_affect_other_stages() -> None:
    """HV-012 pipeline-isolation category, complementing the mixed-outcome
    test above from the other direction: a fixture with valid MRZ/Barcode
    markers but NO OCR marker (so OCR itself lands on INCONCLUSIVE/
    UNREADABLE) must not drag Quality/Classification/MRZ/Barcode down
    with it -- OCR's own inability to recognize text is not evidence of
    anything about the other stages."""
    tenant_id = f"tenant-docproc-ocr-partial-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    mrz_marker = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")
    barcode_marker = b"PAXLI_TEST_BARCODE_VALID:PDF417:document_number=A1234567\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE"
            + mrz_marker + barcode_marker,
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        classification = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_CLASSIFICATION"
        )
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value
        assert classification is not None
        assert classification.status == EvidenceResultStatus.PASS.value
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.PASS.value
        assert barcode is not None
        assert barcode.status == EvidenceResultStatus.PASS.value
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.INCONCLUSIVE.value  # unaffected by others
        assert ocr.reason_codes_json == ["OCR_UNREADABLE"]


async def test_ocr_processing_now_feeds_document_field_extraction() -> None:
    """DP-008/DP-009 Phase 4: supersedes the Phase-3-scoped
    test_ocr_processing_never_writes_document_field_extraction, whose
    premise (DOCUMENT_FIELD_EXTRACTION stays untouched, per DP-005
    Decision 0/11's Phase-3 boundary) is now obsolete by design -- OCR's
    output is exactly one of DOCUMENT_FIELD_EXTRACTION's three real
    inputs. This is the basic sanity check that the new sixth stage
    actually runs and actually reconciles OCR's data; the full round-
    trip/freshness/conflict test battery below covers the rest."""
    tenant_id = f"tenant-docproc-ocr-feeds-reconciliation-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    marker = b"PAXLI_TEST_OCR_VALID:surname=ERIKSSON;given_names=ANNA MARIA\x00"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + marker,
        )
        await session.commit()

    processor = _processor(key_id, storage)
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.PASS.value

        field_extraction = await _effective_result(
            session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION"
        )
        assert field_extraction is not None
        assert field_extraction.status == EvidenceResultStatus.PASS.value


async def test_unexpected_capability_exception_propagates_uncaught() -> None:
    """DP-002 reconciliation amendment B: only CapabilityUnavailableError
    is caught. A bug in a capability implementation must remain
    observable, never silently normalized into an ordinary-looking
    UNAVAILABLE result -- this is the test that would have caught the
    original 'catch bare Exception' draft before it shipped."""
    tenant_id = f"tenant-docproc-defect-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    processor = _processor(key_id, storage, quality_assessor=_BuggyQualityAssessor())

    # asyncio.gather (no return_exceptions=True) re-raises the failing
    # task's own exception type directly, not wrapped -- confirmed here
    # rather than assumed, since this is the one assertion this whole
    # amendment exists to prove.
    with pytest.raises(AttributeError, match="simulated programming defect"):
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        # No DOCUMENT_QUALITY row was fabricated to paper over the defect.
        assert await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY") is None


async def test_mrz_parser_unexpected_exception_propagates_uncaught() -> None:
    """HV-011: the same exception-taxonomy proof as above, for the new
    MRZParser capability boundary specifically -- not assumed inherited
    from the generic CapabilityUnavailableError-only catch, confirmed
    directly for this new call site."""
    tenant_id = f"tenant-docproc-mrz-defect-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE",
        )
        await session.commit()

    processor = _processor(key_id, storage, mrz_parser=_BuggyMRZParser())

    with pytest.raises(AttributeError, match="simulated programming defect"):
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        assert await _effective_result(session, session_id, tenant_id, "MRZ") is None
        # Stages ordered before MRZ (quality/classification) are unaffected
        # by a later stage's defect -- confirms the defect doesn't corrupt
        # or roll back already-committed sibling work.
        quality = await _effective_result(session, session_id, tenant_id, "DOCUMENT_QUALITY")
        assert quality is not None
        assert quality.status == EvidenceResultStatus.PASS.value


async def test_barcode_decoder_unexpected_exception_propagates_uncaught() -> None:
    """HV-011: same proof for BarcodeDecoder specifically."""
    tenant_id = f"tenant-docproc-barcode-defect-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE",
        )
        await session.commit()

    processor = _processor(key_id, storage, barcode_decoder=_BuggyBarcodeDecoder())

    with pytest.raises(AttributeError, match="simulated programming defect"):
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        assert await _effective_result(session, session_id, tenant_id, "BARCODE_QR") is None
        # MRZ (ordered before barcode) already committed successfully and
        # is unaffected by barcode's later defect.
        mrz = await _effective_result(session, session_id, tenant_id, "MRZ")
        assert mrz is not None
        assert mrz.status == EvidenceResultStatus.NOT_SUBMITTED.value


async def test_ocr_engine_unexpected_exception_propagates_uncaught() -> None:
    """HV-012: same proof for OCREngine specifically."""
    tenant_id = f"tenant-docproc-ocr-defect-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE",
        )
        await session.commit()

    processor = _processor(key_id, storage, ocr_engine=_BuggyOCREngine())

    with pytest.raises(AttributeError, match="simulated programming defect"):
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        assert await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION") is None
        # Stages ordered before OCR (barcode) already committed
        # successfully and are unaffected by OCR's later defect.
        barcode = await _effective_result(session, session_id, tenant_id, "BARCODE_QR")
        assert barcode is not None
        assert barcode.status == EvidenceResultStatus.NOT_SUBMITTED.value


async def test_field_reconciler_unexpected_exception_propagates_uncaught() -> None:
    """DP-009 §3: DocumentFieldReconciler has no CapabilityUnavailableError
    analog at all -- ANY exception out of reconcile() is necessarily a
    programming defect, propagating uncaught exactly like every other
    unexpected exception in this pipeline (DP-002 reconciliation
    amendment B)."""
    tenant_id = f"tenant-docproc-field-extraction-defect-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(
            session, tenant_id, session_id, storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE",
        )
        await session.commit()

    processor = _processor(key_id, storage, field_reconciler=_BuggyFieldReconciler())

    with pytest.raises(AttributeError, match="simulated programming defect"):
        await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        assert (
            await _effective_result(session, session_id, tenant_id, "DOCUMENT_FIELD_EXTRACTION")
            is None
        )
        # Every stage ordered before field extraction (all five others)
        # already committed successfully and is unaffected by this
        # stage's later defect.
        ocr = await _effective_result(session, session_id, tenant_id, "OCR_EXTRACTION")
        assert ocr is not None
        assert ocr.status == EvidenceResultStatus.INCONCLUSIVE.value


async def test_document_unsupported_lets_policy_not_document_processor_decide_outcome() -> None:
    """DP-001 Decision 5: DOCUMENT_UNSUPPORTED is an evidence-level
    outcome, never a session-level verdict DocumentProcessor itself
    determines. Two policies, identical unrecognized-document evidence,
    two different final outcomes -- proving the separation is real, not
    just documented. Drives the full real /submit path (workflow ->
    DocumentProcessor -> DecisionOrchestrator -> persisted decision),
    matching test_decision_orchestration.py's full-pipeline pattern one
    layer up."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})

    async def _decide(rule_outcome: DecisionOutcome, reason_code: str) -> DecisionOutcome:
        tenant_id = f"tenant-docproc-separation-{uuid4()}"
        async with session_factory() as session:
            policy_service = PolicyService(
                SqlAlchemyVerificationPolicyRepository(session),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                EvidenceResultSchemaCatalog(),
            )
            await policy_service.create_and_activate(
                tenant_id=tenant_id,
                policy_id="policy-docproc-separation",
                assurance_level=AssuranceLevel.STANDARD,
                created_by="admin",
                evidence_requirements=(
                    EvidenceRequirement(
                        evidence_type="DOCUMENT_CLASSIFICATION",
                        level=EvidenceRequirementLevel.REQUIRED,
                    ),
                ),
                rules=(
                    Rule(
                        id="r1",
                        condition=EvidenceCondition(
                            evidence_type="DOCUMENT_CLASSIFICATION",
                            field="status",
                            operator="==",
                            expected_value="FAIL",
                        ),
                        outcome=rule_outcome,
                        priority=10,
                        reason_code=reason_code,
                    ),
                ),
            )
            session_service = VerificationSessionService(
                SqlAlchemyVerificationSessionRepository(session),
                audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
                policy_service=policy_service,
                session_ttl_minutes=30,
            )
            created_session = await session_service.create(
                tenant_id=tenant_id,
                external_reference=None,
                assurance_level=AssuranceLevel.STANDARD,
            )
            await session.commit()

        async with session_factory() as session:
            await _upload_document(
                session, tenant_id, str(created_session.id), storage,
                MINIMAL_JPEG_BYTES + b"0" * 2000 + b"not a recognized document at all",
            )
            await session.commit()

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
            evidence_result_service = EvidenceResultService(
                SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                SqlAlchemyEvidenceRepository(session),
            )
            audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
            persistence_service = DecisionPersistenceService(
                SqlAlchemyDecisionRepository(session), audit_service
            )
            orchestrator = DecisionOrchestrator(
                session_service, policy_service, evidence_result_service,
                persistence_service, audit_service,
            )
            document_processor = SqlAlchemyDocumentProcessor(
                session_factory, key_provider, key_id, storage,
                DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
                DeterministicMRZParser(), DeterministicBarcodeDecoder(),
                DeterministicOCREngine(), DeterministicFieldReconciler(),
            )
            workflow = VerificationWorkflowService(
                session_service, orchestrator, audit_service, document_processor
            )
            _session, decision = await workflow.submit(
                session_id=created_session.id, tenant_id=tenant_id
            )
            await session.commit()
        return decision.outcome

    rejected = await _decide(DecisionOutcome.REJECTED, "POLICY:DOCUMENT_REJECTED")
    review_required = await _decide(DecisionOutcome.REVIEW_REQUIRED, "POLICY:DOCUMENT_REVIEW")

    assert rejected is DecisionOutcome.REJECTED
    assert review_required is DecisionOutcome.REVIEW_REQUIRED


async def test_mrz_check_digit_mismatch_lets_policy_not_document_processor_decide_outcome() -> None:
    """DP-004 §8/§12 closure criterion: 'a policy can require and
    condition on either [MRZ/BARCODE_QR] type today through the
    unmodified Decision Engine' -- demonstrated end to end via a real
    /submit call driven by MRZ evidence specifically, mirroring the
    DOCUMENT_CLASSIFICATION version of this same proof above."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    corrupted_line2 = _MRZ_LINE2[:9] + "5" + _MRZ_LINE2[10:]
    marker = b"PAXLI_TEST_MRZ:" + (_MRZ_LINE1 + corrupted_line2).encode("ascii")

    tenant_id = f"tenant-docproc-mrz-policy-{uuid4()}"
    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-docproc-mrz",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            evidence_requirements=(
                EvidenceRequirement(evidence_type="MRZ", level=EvidenceRequirementLevel.REQUIRED),
            ),
            rules=(
                Rule(
                    id="r1",
                    condition=EvidenceCondition(
                        evidence_type="MRZ", field="status", operator="==", expected_value="FAIL",
                    ),
                    outcome=DecisionOutcome.REJECTED,
                    priority=10,
                    reason_code="POLICY:MRZ_CHECK_DIGIT_MISMATCH",
                ),
            ),
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    async with session_factory() as session:
        await _upload_document(
            session, tenant_id, str(created_session.id), storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE" + marker,
        )
        await session.commit()

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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        persistence_service = DecisionPersistenceService(
            SqlAlchemyDecisionRepository(session), audit_service
        )
        orchestrator = DecisionOrchestrator(
            session_service, policy_service, evidence_result_service,
            persistence_service, audit_service,
        )
        document_processor = SqlAlchemyDocumentProcessor(
            session_factory, key_provider, key_id, storage,
            DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
            DeterministicMRZParser(), DeterministicBarcodeDecoder(),
            DeterministicOCREngine(), DeterministicFieldReconciler(),
        )
        workflow = VerificationWorkflowService(
            session_service, orchestrator, audit_service, document_processor
        )
        _session, decision = await workflow.submit(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    assert decision.outcome is DecisionOutcome.REJECTED
    assert "POLICY:MRZ_CHECK_DIGIT_MISMATCH" in decision.reason_codes


async def test_ocr_unreadable_lets_policy_not_document_processor_decide_outcome() -> None:
    """DP-006 §7: the same policy-visibility proof, driven by OCR_EXTRACTION
    specifically. OCR has no FAIL member (DP-005 Decision 2), so unlike
    the MRZ version above the rule conditions on OCR's own actual negative
    outcome, INCONCLUSIVE (UNREADABLE) -- proving the Decision Engine sees
    and can act on OCR's real vocabulary, not a borrowed MRZ shape."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})

    tenant_id = f"tenant-docproc-ocr-policy-{uuid4()}"
    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-docproc-ocr",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            evidence_requirements=(
                EvidenceRequirement(
                    evidence_type="OCR_EXTRACTION", level=EvidenceRequirementLevel.REQUIRED
                ),
            ),
            rules=(
                Rule(
                    id="r1",
                    condition=EvidenceCondition(
                        evidence_type="OCR_EXTRACTION",
                        field="status",
                        operator="==",
                        expected_value="INCONCLUSIVE",
                    ),
                    outcome=DecisionOutcome.REVIEW_REQUIRED,
                    priority=10,
                    reason_code="POLICY:OCR_UNREADABLE",
                ),
            ),
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    async with session_factory() as session:
        await _upload_document(
            session, tenant_id, str(created_session.id), storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_OCR_UNREADABLE",
        )
        await session.commit()

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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        persistence_service = DecisionPersistenceService(
            SqlAlchemyDecisionRepository(session), audit_service
        )
        orchestrator = DecisionOrchestrator(
            session_service, policy_service, evidence_result_service,
            persistence_service, audit_service,
        )
        document_processor = SqlAlchemyDocumentProcessor(
            session_factory, key_provider, key_id, storage,
            DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
            DeterministicMRZParser(), DeterministicBarcodeDecoder(),
            DeterministicOCREngine(), DeterministicFieldReconciler(),
        )
        workflow = VerificationWorkflowService(
            session_service, orchestrator, audit_service, document_processor
        )
        _session, decision = await workflow.submit(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    assert decision.outcome is DecisionOutcome.REVIEW_REQUIRED
    assert "POLICY:OCR_UNREADABLE" in decision.reason_codes


async def test_document_field_extraction_conflict_lets_policy_not_document_processor_decide_outcome() -> None:  # noqa: E501
    """DP-009 §9: the same policy-visibility proof, driven by
    DOCUMENT_FIELD_EXTRACTION specifically -- a genuine cross-source
    surname disagreement (OCR vs MRZ), proving the Decision Engine sees
    and can act on the sixth stage's own real vocabulary
    (conflicted_fields -> FIELD_VALUE_CONFLICT), not a borrowed shape
    from any of the five stages before it."""
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})

    tenant_id = f"tenant-docproc-field-extraction-policy-{uuid4()}"
    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-docproc-field-extraction",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            evidence_requirements=(
                EvidenceRequirement(
                    evidence_type="DOCUMENT_FIELD_EXTRACTION",
                    level=EvidenceRequirementLevel.REQUIRED,
                ),
            ),
            rules=(
                Rule(
                    id="r1",
                    condition=EvidenceCondition(
                        evidence_type="DOCUMENT_FIELD_EXTRACTION",
                        field="status",
                        operator="==",
                        expected_value="INCONCLUSIVE",
                    ),
                    outcome=DecisionOutcome.REJECTED,
                    priority=10,
                    reason_code="POLICY:FIELD_VALUE_CONFLICT",
                ),
            ),
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    async with session_factory() as session:
        mrz_marker = b"PAXLI_TEST_MRZ:" + _MRZ_VALID_RAW.encode("ascii")  # real surname ERIKSSON
        ocr_marker = b"PAXLI_TEST_OCR_VALID:surname=MULLER\x00"  # disagrees deliberately
        await _upload_document(
            session, tenant_id, str(created_session.id), storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE"
            + mrz_marker + ocr_marker,
        )
        await session.commit()

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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        persistence_service = DecisionPersistenceService(
            SqlAlchemyDecisionRepository(session), audit_service
        )
        orchestrator = DecisionOrchestrator(
            session_service, policy_service, evidence_result_service,
            persistence_service, audit_service,
        )
        document_processor = SqlAlchemyDocumentProcessor(
            session_factory, key_provider, key_id, storage,
            DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
            DeterministicMRZParser(), DeterministicBarcodeDecoder(),
            DeterministicOCREngine(), DeterministicFieldReconciler(),
        )
        workflow = VerificationWorkflowService(
            session_service, orchestrator, audit_service, document_processor
        )
        _session, decision = await workflow.submit(
            session_id=created_session.id, tenant_id=tenant_id
        )
        await session.commit()

    assert decision.outcome is DecisionOutcome.REJECTED
    assert "POLICY:FIELD_VALUE_CONFLICT" in decision.reason_codes


async def test_concurrent_submit_with_a_real_document_converges_on_one_decision() -> None:
    """HV-010 category 5: the SAME race
    test_submit_api_wiring.py's test_workflow_service_di_wiring_concurrent_
    submit_converges already proves at the workflow-DI level, but that
    test uploads no evidence at all, so DocumentProcessor always took its
    zero-captures no-op path there -- it never actually exercised
    DocumentProcessor under concurrency. workflow.py's submit() has no CAS
    gate immediately around document_processor.process() itself: the CAS
    transition into PROCESSING only gates WHICH caller performs that one
    hop, but both a winner that just transitioned in and a caller that
    independently finds the session already sitting in PROCESSING land in
    the same branch and both call document_processor.process() -- so this
    race is genuinely reachable through the real submit() entrypoint, not
    a scenario invented only at the DocumentProcessor layer. With a real
    DOCUMENT evidence capture present, drives two full concurrent
    submit() calls through the DI-equivalent stack and confirms they
    converge on one decision AND exactly one effective row per document
    evidence-result type, closing the loop from the isolated
    DocumentProcessor-level proof
    (test_concurrent_process_calls_converge_on_one_effective_result_per_type)
    up through the real public entrypoint."""
    tenant_id = f"tenant-docproc-submit-race-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})

    async with session_factory() as session:
        policy_service = PolicyService(
            SqlAlchemyVerificationPolicyRepository(session),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            EvidenceResultSchemaCatalog(),
        )
        await policy_service.create_and_activate(
            tenant_id=tenant_id,
            policy_id="policy-docproc-submit-race",
            assurance_level=AssuranceLevel.STANDARD,
            created_by="admin",
            default_outcome=DecisionOutcome.INCONCLUSIVE,
        )
        session_service = VerificationSessionService(
            SqlAlchemyVerificationSessionRepository(session),
            audit_service=AuditService(SqlAlchemyAuditEventRepository(session)),
            policy_service=policy_service,
            session_ttl_minutes=30,
        )
        created_session = await session_service.create(
            tenant_id=tenant_id, external_reference=None, assurance_level=AssuranceLevel.STANDARD
        )
        await session.commit()

    async with session_factory() as session:
        capture_id = await _upload_document(
            session, tenant_id, str(created_session.id), storage,
            MINIMAL_JPEG_BYTES + b"0" * 2000 + b"PAXLI_TEST_STANDARD_NIN_SLIP",
        )
        await session.commit()

    def _build_workflow(session: AsyncSession) -> VerificationWorkflowService:
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
        evidence_result_service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        audit_service = AuditService(SqlAlchemyAuditEventRepository(session))
        persistence_service = DecisionPersistenceService(
            SqlAlchemyDecisionRepository(session), audit_service
        )
        orchestrator = DecisionOrchestrator(
            session_service, policy_service, evidence_result_service,
            persistence_service, audit_service,
        )
        document_processor = SqlAlchemyDocumentProcessor(
            session_factory, key_provider, key_id, storage,
            DeterministicQualityAssessor(), DeterministicDocumentClassifier(),
            DeterministicMRZParser(), DeterministicBarcodeDecoder(),
            DeterministicOCREngine(), DeterministicFieldReconciler(),
        )
        return VerificationWorkflowService(
            session_service, orchestrator, audit_service, document_processor
        )

    async def _submit_attempt() -> UUID:
        async with session_factory() as session:
            workflow = _build_workflow(session)
            _session, decision = await workflow.submit(
                session_id=created_session.id, tenant_id=tenant_id
            )
            await session.commit()
            return decision.decision_id

    decision_ids = await asyncio.gather(_submit_attempt(), _submit_attempt())
    assert decision_ids[0] == decision_ids[1]

    async with session_factory() as session:
        for evidence_type in ("DOCUMENT_QUALITY", "DOCUMENT_CLASSIFICATION"):
            effective_rows = (
                await session.execute(
                    select(EvidenceResultRecord).where(
                        EvidenceResultRecord.session_id == str(created_session.id),
                        EvidenceResultRecord.evidence_type == evidence_type,
                        EvidenceResultRecord.is_effective.is_(True),
                    )
                )
            ).scalars().all()
            assert len(effective_rows) == 1, (
                f"{evidence_type}: expected exactly one effective row, got {len(effective_rows)}"
            )
            assert effective_rows[0].source_reference == str(capture_id)
