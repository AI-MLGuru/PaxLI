"""BD-001 Slice G (BD-001.2): real Postgres + MinIO integration tests
for DocumentBoundReferenceResolver -- the orchestration boundary
between a DOCUMENT capture's effective DOCUMENT_FIELD_EXTRACTION row
and a transient ReferenceResolution. Tested here rather than as a pure
unit test against fakes, mirroring test_document_processor.py's own
convention exactly: this resolver constructs real SQLAlchemy
repositories internally against session_factory -- there is no
fake-repository seam to unit-test against. DocumentFaceExtractor's own
decode/cardinality/crop logic is already covered by pure unit tests
(tests/unit/test_insightface_document_face_extractor.py); this file
tests only the resolver's own precondition/translation logic, using a
fixed-result double rather than the real InsightFace adapter.

Skipped when Postgres and/or MinIO aren't reachable, mirroring
test_document_processor.py.
"""

import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest

from apps.api.paxli_api.config import get_settings
from core.audit.service import AuditService
from core.evidence.enums import EvidenceSource, EvidenceType
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.service import EvidenceResultService
from core.face.capabilities import CapabilityUnavailableError, DocumentFaceExtractor
from core.face.reference import ReferenceAcquisitionOutcome
from core.face.types import DocumentFaceExtractionOutcome, DocumentFaceExtractionResult
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
from infrastructure.database.session import session_factory
from infrastructure.face.document_reference_resolver import DocumentBoundReferenceResolver
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
) -> str:
    """Mirrors test_document_processor.py's own helper exactly."""
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
    return object_key


async def _seed_field_extraction(
    session,
    tenant_id: str,
    session_id: str,
    key_id: str,
    *,
    status: EvidenceResultStatus,
) -> UUID:
    """Seeds a DOCUMENT_FIELD_EXTRACTION row directly via
    EvidenceResultService.create() -- bypasses running the real
    document pipeline (already covered by test_document_processor.py)
    so this file can isolate the resolver's own precondition logic
    against every status combination directly. `result=None` is valid
    for any status (core.evidence_result.schemas.validate_result_payload
    always allows it) -- DocumentBoundReferenceResolver never reads
    this row's `result` payload, only its `id`/`status`, so no content
    is needed here."""
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    service = EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        SqlAlchemyEvidenceRepository(session),
    )
    saved = await service.create(
        tenant_id=tenant_id,
        session_id=UUID(session_id),
        evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
        status=status,
        producer="test-field-extraction-seed",
        producer_version="1.0",
    )
    return saved.id


class _FixedDocumentFaceExtractor(DocumentFaceExtractor):
    """A real class, not a mock -- matches this project's established
    failure-injection convention (test_document_processor.py's own
    _Counting*/_Unavailable* doubles)."""

    def __init__(self, result: DocumentFaceExtractionResult) -> None:
        self._result = result
        self.calls = 0

    async def extract_candidate(self, image: bytes) -> DocumentFaceExtractionResult:
        self.calls += 1
        return self._result


class _UnavailableDocumentFaceExtractor(DocumentFaceExtractor):
    async def extract_candidate(self, image: bytes) -> DocumentFaceExtractionResult:
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


def _resolver(
    key_id: str, storage, extractor: DocumentFaceExtractor
) -> DocumentBoundReferenceResolver:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return DocumentBoundReferenceResolver(session_factory, key_provider, key_id, storage, extractor)


async def test_resolve_reports_not_available_for_zero_document_captures() -> None:
    tenant_id = f"tenant-refresolver-zero-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(outcome=DocumentFaceExtractionOutcome.VALID, image=b"x")
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is ReferenceAcquisitionOutcome.NOT_AVAILABLE
    assert resolution.identity is None
    assert extractor.calls == 0


async def test_resolve_reports_not_available_for_two_document_captures() -> None:
    tenant_id = f"tenant-refresolver-ambiguous-capture-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(outcome=DocumentFaceExtractionOutcome.VALID, image=b"x")
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is ReferenceAcquisitionOutcome.NOT_AVAILABLE
    assert extractor.calls == 0


async def test_resolve_reports_not_available_when_field_extraction_not_yet_effective() -> None:
    tenant_id = f"tenant-refresolver-no-extraction-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(outcome=DocumentFaceExtractionOutcome.VALID, image=b"x")
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is ReferenceAcquisitionOutcome.NOT_AVAILABLE
    assert extractor.calls == 0


async def test_resolve_reports_not_available_when_field_extraction_unavailable() -> None:
    tenant_id = f"tenant-refresolver-extraction-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await _seed_field_extraction(
            session, tenant_id, session_id, key_id, status=EvidenceResultStatus.UNAVAILABLE
        )
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(outcome=DocumentFaceExtractionOutcome.VALID, image=b"x")
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is ReferenceAcquisitionOutcome.NOT_AVAILABLE
    assert extractor.calls == 0


@pytest.mark.parametrize(
    ("extractor_outcome", "expected"),
    [
        (DocumentFaceExtractionOutcome.UNREADABLE, ReferenceAcquisitionOutcome.NOT_AVAILABLE),
        (DocumentFaceExtractionOutcome.NO_FACE, ReferenceAcquisitionOutcome.NO_FACE_FOUND),
        (DocumentFaceExtractionOutcome.AMBIGUOUS, ReferenceAcquisitionOutcome.AMBIGUOUS),
    ],
)
async def test_resolve_translates_extractor_outcomes(
    extractor_outcome: DocumentFaceExtractionOutcome,
    expected: ReferenceAcquisitionOutcome,
) -> None:
    tenant_id = f"tenant-refresolver-translate-{extractor_outcome.value}-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await _seed_field_extraction(
            session, tenant_id, session_id, key_id, status=EvidenceResultStatus.PASS
        )
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(outcome=extractor_outcome, image=None)
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is expected
    assert resolution.identity is None
    assert extractor.calls == 1


async def test_resolve_resolved_from_inconclusive_field_conflict_row() -> None:
    """BD-001.1 G-4's separation, confirmed live: a DOCUMENT_FIELD_EXTRACTION
    row at status=INCONCLUSIVE (the field-conflict case -- exactly one
    DOCUMENT capture exists, so this cannot be the ambiguous-capture
    case, already independently ruled out by the resolver's own step 2)
    does not block reference acquisition. Field-level conflicts are
    unrelated to whether the document's photo region contains a usable
    face."""
    tenant_id = f"tenant-refresolver-inconclusive-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await _seed_field_extraction(
            session, tenant_id, session_id, key_id, status=EvidenceResultStatus.INCONCLUSIVE
        )
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(outcome=DocumentFaceExtractionOutcome.VALID, image=b"cropped")
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is ReferenceAcquisitionOutcome.RESOLVED
    assert resolution.identity is not None


async def test_resolve_resolved_reference_identity_fields_are_correct() -> None:
    tenant_id = f"tenant-refresolver-resolved-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        field_extraction_id = await _seed_field_extraction(
            session, tenant_id, session_id, key_id, status=EvidenceResultStatus.PASS
        )
        await session.commit()

    extractor = _FixedDocumentFaceExtractor(
        DocumentFaceExtractionResult(
            outcome=DocumentFaceExtractionOutcome.VALID, image=b"cropped-face-bytes"
        )
    )
    resolver = _resolver(key_id, storage, extractor)
    resolution = await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)

    assert resolution.outcome is ReferenceAcquisitionOutcome.RESOLVED
    assert resolution.identity is not None
    identity = resolution.identity
    assert identity.identity_claim == field_extraction_id
    assert identity.provenance.acquisition_route == "DOCUMENT_BOUND"
    assert identity.provenance.source_evidence_result_ids == (field_extraction_id,)
    assert identity.reference_artifact.kind == "IMAGE"
    assert identity.reference_artifact.image == b"cropped-face-bytes"


async def test_resolve_propagates_capability_unavailable_error_uncaught() -> None:
    """BD-001.2 D-3: a genuine provider/runtime failure from
    DocumentFaceExtractor propagates out of resolve() uncaught -- this
    resolver persists nothing and has no legitimate place to catch and
    reinterpret it as NOT_AVAILABLE."""
    tenant_id = f"tenant-refresolver-capability-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_document(session, tenant_id, session_id, storage, MINIMAL_JPEG_BYTES)
        await _seed_field_extraction(
            session, tenant_id, session_id, key_id, status=EvidenceResultStatus.PASS
        )
        await session.commit()

    resolver = _resolver(key_id, storage, _UnavailableDocumentFaceExtractor())

    with pytest.raises(CapabilityUnavailableError):
        await resolver.resolve(session_id=UUID(session_id), tenant_id=tenant_id)
