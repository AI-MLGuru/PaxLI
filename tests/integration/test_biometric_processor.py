"""BD-001 Slice G.2 (BD-001.7/BD-001.8): real Postgres + MinIO
integration tests for BiometricProcessor -- the orchestration boundary
between a resolved reference/probe artifact and typed, lineage-bearing
FACE_DETECTION_*/FACE_QUALITY_*/FACE_EMBEDDING_*/FACE_MATCH
EvidenceResult rows.

Tested here rather than as pure unit tests against fakes, mirroring
test_document_processor.py's own convention exactly: BiometricProcessor
constructs real SQLAlchemy repositories internally against
session_factory -- there is no fake-repository seam to unit-test
against. The five capability/resolver dependencies DO have a fake
seam and are exercised via real classes (not mocks), matching this
project's established _Counting*/_Unavailable*/_Fixed* convention.
FaceMatcher uses the real CosineFaceMatcher (pure computation, no
vendor dependency) rather than a fake -- there is no reason to fake
pure arithmetic.

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
from core.evidence_result.exceptions import InvalidSupersessionError
from core.evidence_result.models import ModelReference
from core.evidence_result.service import EvidenceResultService
from core.face.capabilities import (
    CapabilityUnavailableError,
    FaceDetector,
    FaceEmbedder,
    FaceQualityAssessor,
)
from core.face.matcher import CosineFaceMatcher
from core.face.reason_codes import FaceReasonCode
from core.face.reference import (
    ReferenceAcquisitionOutcome,
    ReferenceArtifactImage,
    ReferenceIdentity,
    ReferenceProvenance,
    ReferenceResolution,
    ReferenceSourceResolver,
)
from core.face.types import (
    FaceDetection,
    FaceDetectionOutcome,
    FaceEmbedding,
    FaceEmbeddingOutcome,
    FaceQuality,
    FaceQualityOutcome,
)
from infrastructure.database.models.evidence import EvidenceRecord
from infrastructure.database.models.verification_session import VerificationSessionRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository
from infrastructure.database.session import session_factory
from infrastructure.face.processor import BiometricProcessor
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage
from infrastructure.storage.minio import MinioObjectStorage

_MODEL_REFERENCE = ModelReference(model_id="test-model", model_version="1.0")


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


async def _upload_selfie(
    session, tenant_id: str, session_id: str, storage, content: bytes = b"selfie"
) -> UUID:
    evidence_id = uuid4()
    checksum = f"selfie-{uuid4()}"
    object_key = f"{tenant_id}/{session_id}/selfie/{checksum}"
    await storage.put(object_key, content, "image/jpeg")
    session.add(
        EvidenceRecord(
            id=str(evidence_id),
            session_id=session_id,
            tenant_id=tenant_id,
            evidence_type=EvidenceType.SELFIE.value,
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


def _service(session, key_id: str) -> EvidenceResultService:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return EvidenceResultService(
        SqlAlchemyEvidenceResultRepository(session, key_provider, key_id),
        AuditService(SqlAlchemyAuditEventRepository(session)),
        SqlAlchemyEvidenceRepository(session),
    )


async def _seed_identity_claim(session, tenant_id: str, session_id: str, key_id: str) -> UUID:
    """A minimal real EvidenceResult standing in for a
    DOCUMENT_FIELD_EXTRACTION row -- ReferenceIdentity.identity_claim
    must reference a genuinely existing row in this tenant/session, or
    _validate_provenance rejects it as forged."""
    service = _service(session, key_id)
    row = await service.create(
        tenant_id=tenant_id,
        session_id=UUID(session_id),
        evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
        status=EvidenceResultStatus.PASS,
        producer="test-identity-claim-seed",
        producer_version="1.0",
    )
    return row.id


def _resolved(identity_claim: UUID, image: bytes = b"reference") -> ReferenceResolution:
    return ReferenceResolution(
        outcome=ReferenceAcquisitionOutcome.RESOLVED,
        identity=ReferenceIdentity(
            identity_claim=identity_claim,
            reference_artifact=ReferenceArtifactImage(kind="IMAGE", image=image),
            provenance=ReferenceProvenance(
                acquisition_route="DOCUMENT_BOUND", source_evidence_result_ids=(identity_claim,)
            ),
        ),
    )


def _not_available() -> ReferenceResolution:
    return ReferenceResolution(outcome=ReferenceAcquisitionOutcome.NOT_AVAILABLE, identity=None)


def _no_face_found() -> ReferenceResolution:
    return ReferenceResolution(outcome=ReferenceAcquisitionOutcome.NO_FACE_FOUND, identity=None)


class _FixedReferenceSourceResolver(ReferenceSourceResolver):
    def __init__(self, resolution: ReferenceResolution) -> None:
        self._resolution = resolution
        self.calls = 0

    async def resolve(self, *, session_id: UUID, tenant_id: str) -> ReferenceResolution:
        self.calls += 1
        return self._resolution


class _FixedFaceDetector(FaceDetector):
    def __init__(self, result: FaceDetection) -> None:
        self._result = result
        self.calls = 0

    async def detect(self, image: bytes) -> FaceDetection:
        self.calls += 1
        return self._result


class _UnavailableFaceDetector(FaceDetector):
    async def detect(self, image: bytes) -> FaceDetection:
        raise CapabilityUnavailableError("MODEL_UNAVAILABLE")


class _FixedFaceQualityAssessor(FaceQualityAssessor):
    def __init__(self, result: FaceQuality) -> None:
        self._result = result
        self.calls = 0

    async def assess(self, image: bytes) -> FaceQuality:
        self.calls += 1
        return self._result


class _FixedFaceEmbedder(FaceEmbedder):
    def __init__(self, result: FaceEmbedding) -> None:
        self._result = result
        self.calls = 0

    async def embed(self, image: bytes) -> FaceEmbedding:
        self.calls += 1
        return self._result


def _valid_detection() -> FaceDetection:
    return FaceDetection(outcome=FaceDetectionOutcome.VALID, detected=True, face_count=1)


def _valid_quality(score: float = 0.9) -> FaceQuality:
    return FaceQuality(outcome=FaceQualityOutcome.VALID, quality_score=score)


def _valid_embedding(vector: tuple[float, ...] = (1.0, 0.0, 0.0)) -> FaceEmbedding:
    return FaceEmbedding(
        outcome=FaceEmbeddingOutcome.VALID,
        embedding=vector,
        embedding_dimensions=len(vector),
        model_reference=_MODEL_REFERENCE,
    )


def _processor(
    key_id: str,
    storage,
    *,
    reference_source: ReferenceSourceResolver,
    face_detector: FaceDetector,
    face_quality_assessor: FaceQualityAssessor,
    face_embedder: FaceEmbedder,
) -> BiometricProcessor:
    key_provider = LocalAesGcmKeyProvider({key_id: b"0" * 32})
    return BiometricProcessor(
        session_factory,
        key_provider,
        key_id,
        storage,
        face_detector,
        face_quality_assessor,
        face_embedder,
        CosineFaceMatcher(),
        reference_source,
    )


# ---------------------------------------------------------------------------
# Reference-side outcome handling
# ---------------------------------------------------------------------------


async def test_reference_not_available_persists_nothing() -> None:
    tenant_id = f"tenant-g2-ref-not-available-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_not_available())
    detector = _FixedFaceDetector(_valid_detection())
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=detector,
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding()),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert detector.calls == 0
    async with session_factory() as session:
        service = _service(session, key_id)
        row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
        )
        assert row is None


async def test_reference_no_face_found_persists_detection_only() -> None:
    tenant_id = f"tenant-g2-ref-no-face-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_no_face_found())
    detector = _FixedFaceDetector(_valid_detection())
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=detector,
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding()),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert detector.calls == 0  # no capability invocation -- BD-001.7 §3a
    async with session_factory() as session:
        service = _service(session, key_id)
        detection_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
        )
        assert detection_row is not None
        assert detection_row.status == EvidenceResultStatus.INCONCLUSIVE
        assert detection_row.reason_codes == (FaceReasonCode.REFERENCE_NO_FACE_FOUND.value,)
        assert detection_row.parent_evidence_result_ids == ()

        quality_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
        )
        embedding_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
        )
        assert quality_row is None
        assert embedding_row is None


async def test_reference_resolved_runs_full_chain() -> None:
    tenant_id = f"tenant-g2-ref-resolved-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_resolved(identity_claim))
    detector = _FixedFaceDetector(_valid_detection())
    quality_assessor = _FixedFaceQualityAssessor(_valid_quality())
    embedder = _FixedFaceEmbedder(_valid_embedding())
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=detector,
        face_quality_assessor=quality_assessor,
        face_embedder=embedder,
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert detector.calls == 1
    assert quality_assessor.calls == 1
    assert embedder.calls == 1
    async with session_factory() as session:
        service = _service(session, key_id)
        detection_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
        )
        quality_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
        )
        embedding_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
        )
        assert detection_row is not None and detection_row.status == EvidenceResultStatus.PASS
        assert detection_row.parent_evidence_result_ids == (identity_claim,)
        assert quality_row is not None and quality_row.status == EvidenceResultStatus.PASS
        assert quality_row.parent_evidence_result_ids == (detection_row.id,)
        assert embedding_row is not None and embedding_row.status == EvidenceResultStatus.PASS
        assert embedding_row.parent_evidence_result_ids == (quality_row.id,)


async def test_low_quality_score_does_not_prevent_embedding() -> None:
    """BD-001 Slice C's frozen 'no gating' decision, proven end to end
    against real persistence, not merely by code inspection: a low
    FaceQuality score is still outcome=VALID (the capability
    successfully assessed a face, it just scored it low), and
    BiometricProcessor must attempt embedding regardless -- FaceQuality
    is independent evidence, never a precondition FaceEmbedder consults.
    Mirrors test_reference_resolved_runs_full_chain exactly, differing
    only in the quality score used."""
    tenant_id = f"tenant-g2-low-quality-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_resolved(identity_claim))
    detector = _FixedFaceDetector(_valid_detection())
    quality_assessor = _FixedFaceQualityAssessor(_valid_quality(0.05))
    embedder = _FixedFaceEmbedder(_valid_embedding())
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=detector,
        face_quality_assessor=quality_assessor,
        face_embedder=embedder,
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    # The embedder must actually have been invoked -- not skipped because
    # the quality score was low.
    assert embedder.calls == 1
    async with session_factory() as session:
        service = _service(session, key_id)
        quality_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
        )
        embedding_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
        )
        # The low score is persisted honestly, as its own independent
        # evidence row -- not hidden, not used to block anything.
        assert quality_row is not None and quality_row.status == EvidenceResultStatus.PASS
        assert quality_row.result is not None
        assert quality_row.result["quality_score"] == pytest.approx(0.05)
        # Embedding still succeeded despite the low quality score.
        assert embedding_row is not None and embedding_row.status == EvidenceResultStatus.PASS
        assert embedding_row.parent_evidence_result_ids == (quality_row.id,)


async def test_reference_detector_unavailable_persists_unavailable_no_downstream() -> None:
    tenant_id = f"tenant-g2-ref-unavailable-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_resolved(identity_claim))
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=_UnavailableFaceDetector(),
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding()),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        detection_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
        )
        assert detection_row is not None
        assert detection_row.status == EvidenceResultStatus.UNAVAILABLE
        quality_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
        )
        assert quality_row is None


# ---------------------------------------------------------------------------
# Probe-side cardinality
# ---------------------------------------------------------------------------


async def test_probe_zero_selfies_persists_nothing() -> None:
    tenant_id = f"tenant-g2-probe-zero-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    detector = _FixedFaceDetector(_valid_detection())
    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_not_available()),
        face_detector=detector,
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding()),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert detector.calls == 0
    async with session_factory() as session:
        service = _service(session, key_id)
        row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_DETECTION_PROBE,
        )
        assert row is None


async def test_probe_two_selfies_persists_ambiguous_across_all_three_stages() -> None:
    tenant_id = f"tenant-g2-probe-ambiguous-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await _upload_selfie(session, tenant_id, session_id, storage, b"selfie-a")
        await _upload_selfie(session, tenant_id, session_id, storage, b"selfie-b")
        await session.commit()

    detector = _FixedFaceDetector(_valid_detection())
    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_not_available()),
        face_detector=detector,
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding()),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    assert detector.calls == 0  # no selection, ever -- no capability call at all
    async with session_factory() as session:
        service = _service(session, key_id)
        for evidence_type in (
            EvidenceResultType.FACE_DETECTION_PROBE,
            EvidenceResultType.FACE_QUALITY_PROBE,
            EvidenceResultType.FACE_EMBEDDING_PROBE,
        ):
            row = await service.get_effective_for_session_by_type(
                session_id=UUID(session_id),
                tenant_id=tenant_id,
                evidence_type=evidence_type,
            )
            assert row is not None
            assert row.status == EvidenceResultStatus.INCONCLUSIVE
            assert row.reason_codes == (FaceReasonCode.AMBIGUOUS_SELFIE_CAPTURE.value,)


async def test_probe_one_selfie_runs_full_chain() -> None:
    tenant_id = f"tenant-g2-probe-one-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        capture_id = await _upload_selfie(session, tenant_id, session_id, storage)
        await session.commit()

    detector = _FixedFaceDetector(_valid_detection())
    quality_assessor = _FixedFaceQualityAssessor(_valid_quality())
    embedder = _FixedFaceEmbedder(_valid_embedding())
    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_not_available()),
        face_detector=detector,
        face_quality_assessor=quality_assessor,
        face_embedder=embedder,
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        detection_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_DETECTION_PROBE,
        )
        assert detection_row is not None
        assert detection_row.source_reference == capture_id
        assert detection_row.parent_evidence_result_ids == ()
        embedding_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
        )
        assert embedding_row is not None and embedding_row.status == EvidenceResultStatus.PASS


# ---------------------------------------------------------------------------
# Freshness (short-circuit vs. recompute)
# ---------------------------------------------------------------------------


async def test_fresh_reference_chain_short_circuits_without_recomputation() -> None:
    tenant_id = f"tenant-g2-ref-fresh-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_resolved(identity_claim))
    detector = _FixedFaceDetector(_valid_detection())
    quality_assessor = _FixedFaceQualityAssessor(_valid_quality())
    embedder = _FixedFaceEmbedder(_valid_embedding())
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=detector,
        face_quality_assessor=quality_assessor,
        face_embedder=embedder,
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert detector.calls == 1 and quality_assessor.calls == 1 and embedder.calls == 1

    # Second call, same identity_claim -- every stage must be reused.
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    assert detector.calls == 1 and quality_assessor.calls == 1 and embedder.calls == 1


# ---------------------------------------------------------------------------
# FaceMatch: trigger, freshness, and the lineage-gap regression
# ---------------------------------------------------------------------------


async def test_face_match_not_attempted_until_both_sides_pass() -> None:
    tenant_id = f"tenant-g2-match-waiting-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await session.commit()

    # Reference side only -- no SELFIE at all.
    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_resolved(identity_claim)),
        face_detector=_FixedFaceDetector(_valid_detection()),
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding()),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        match_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        assert match_row is None


async def test_face_match_computed_when_both_sides_pass() -> None:
    tenant_id = f"tenant-g2-match-computed-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await _upload_selfie(session, tenant_id, session_id, storage)
        await session.commit()

    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_resolved(identity_claim)),
        face_detector=_FixedFaceDetector(_valid_detection()),
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding((1.0, 0.0, 0.0))),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        match_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        assert match_row is not None
        assert match_row.status == EvidenceResultStatus.PASS
        assert match_row.result is not None
        assert match_row.result["similarity"] == pytest.approx(1.0)
        reference_embedding = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
        )
        probe_embedding = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
        )
        assert match_row.parent_evidence_result_ids == (reference_embedding.id, probe_embedding.id)
        assert match_row.result["reference_evidence_result_id"] == str(reference_embedding.id)
        assert match_row.result["probe_evidence_result_id"] == str(probe_embedding.id)


async def test_face_match_incompatible_representations_persist_inconclusive() -> None:
    tenant_id = f"tenant-g2-match-incompatible-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await _upload_selfie(session, tenant_id, session_id, storage)
        await session.commit()

    # Two different embedders producing embeddings with different
    # model_reference values -- FaceMatcher.compare() refuses to score.
    other_model = ModelReference(model_id="other-model", model_version="9.9")

    class _AlternatingEmbedder(FaceEmbedder):
        def __init__(self) -> None:
            self.calls = 0

        async def embed(self, image: bytes) -> FaceEmbedding:
            self.calls += 1
            model = _MODEL_REFERENCE if image == b"reference" else other_model
            return FaceEmbedding(
                outcome=FaceEmbeddingOutcome.VALID,
                embedding=(1.0, 0.0, 0.0),
                embedding_dimensions=3,
                model_reference=model,
            )

    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_resolved(identity_claim)),
        face_detector=_FixedFaceDetector(_valid_detection()),
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_AlternatingEmbedder(),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        match_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        assert match_row is not None
        assert match_row.status == EvidenceResultStatus.INCONCLUSIVE
        assert match_row.reason_codes == (FaceReasonCode.REPRESENTATION_INCOMPATIBLE.value,)
        assert match_row.result is None


async def test_face_match_fresh_existing_match_skips_recomputation() -> None:
    tenant_id = f"tenant-g2-match-fresh-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await _upload_selfie(session, tenant_id, session_id, storage)
        await session.commit()

    processor = _processor(
        key_id,
        storage,
        reference_source=_FixedReferenceSourceResolver(_resolved(identity_claim)),
        face_detector=_FixedFaceDetector(_valid_detection()),
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding((1.0, 0.0, 0.0))),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        first_match = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )

    # Second call, nothing changed -- FaceMatch must not be recomputed
    # (same row id, same produced_at).
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)
    async with session_factory() as session:
        service = _service(session, key_id)
        second_match = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        assert second_match.id == first_match.id


async def test_stale_reference_lineage_excludes_orphaned_embedding_and_invalidates_match() -> None:
    """The exact regression this plan's own revision fixes: after a
    resolved reference chain produces a PASS embedding and a PASS
    FaceMatch, the resolver flips to NO_FACE_FOUND. FACE_QUALITY_
    REFERENCE/FACE_EMBEDDING_REFERENCE remain physically effective
    (BD-001.7 G.2-S11 never touches them) but must be excluded from
    FaceMatch consideration, and the existing match must be invalidated
    -- never left PASS against a now-orphaned embedding."""
    tenant_id = f"tenant-g2-stale-lineage-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await _upload_selfie(session, tenant_id, session_id, storage)
        await session.commit()

    resolver = _FixedReferenceSourceResolver(_resolved(identity_claim))
    processor = _processor(
        key_id,
        storage,
        reference_source=resolver,
        face_detector=_FixedFaceDetector(_valid_detection()),
        face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
        face_embedder=_FixedFaceEmbedder(_valid_embedding((1.0, 0.0, 0.0))),
    )
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        original_match = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        original_embedding = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
        )
        assert original_match is not None and original_match.status == EvidenceResultStatus.PASS

    # Resolution flips -- the document no longer yields a usable face.
    resolver._resolution = _no_face_found()  # noqa: SLF001 -- test-local double, not production code
    await processor.process(session_id=UUID(session_id), tenant_id=tenant_id)

    async with session_factory() as session:
        service = _service(session, key_id)
        # The old embedding row is untouched -- still physically
        # effective, still PASS (BD-001.7 G.2-S11: no cleanup here).
        embedding_after = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
        )
        assert embedding_after.id == original_embedding.id
        assert embedding_after.status == EvidenceResultStatus.PASS

        # But FaceMatch must now be invalidated -- never left PASS
        # against an orphaned embedding.
        match_after = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        assert match_after.id != original_match.id
        assert match_after.status == EvidenceResultStatus.INCONCLUSIVE
        assert match_after.reason_codes == (FaceReasonCode.PARENT_EVIDENCE_NOT_USABLE.value,)
        assert match_after.result is None
        # Only the probe side (still lineage-current) is recorded --
        # BD-001.8 §9's resolution of BD-001.7 §10's deferred detail.
        probe_embedding = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
        )
        assert match_after.parent_evidence_result_ids == (probe_embedding.id,)


# ---------------------------------------------------------------------------
# Concurrency -- two distinct scenarios, not one vague "concurrent" test
# ---------------------------------------------------------------------------


async def test_concurrent_creation_of_face_match_recovers_to_one_winner() -> None:
    tenant_id = f"tenant-g2-concurrent-create-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        identity_claim = await _seed_identity_claim(session, tenant_id, session_id, key_id)
        await _upload_selfie(session, tenant_id, session_id, storage)
        await session.commit()

    def make_processor() -> BiometricProcessor:
        return _processor(
            key_id,
            storage,
            reference_source=_FixedReferenceSourceResolver(_resolved(identity_claim)),
            face_detector=_FixedFaceDetector(_valid_detection()),
            face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
            face_embedder=_FixedFaceEmbedder(_valid_embedding((1.0, 0.0, 0.0))),
        )

    import asyncio

    processor_a, processor_b = make_processor(), make_processor()
    await asyncio.gather(
        processor_a.process(session_id=UUID(session_id), tenant_id=tenant_id),
        processor_b.process(session_id=UUID(session_id), tenant_id=tenant_id),
    )

    async with session_factory() as session:
        service = _service(session, key_id)
        effective = await service.list_effective_for_session(
            session_id=UUID(session_id), tenant_id=tenant_id
        )
        match_rows = [r for r in effective if r.evidence_type is EvidenceResultType.FACE_MATCH]
        assert len(match_rows) == 1


async def test_concurrent_supersession_against_moved_target_raises_uncaught() -> None:
    tenant_id = f"tenant-g2-concurrent-supersede-{uuid4()}"
    key_id = f"key-{uuid4()}"

    async with session_factory() as session:
        session_id = await _create_session(session, tenant_id)
        await session.commit()

    async with session_factory() as session:
        service = _service(session, key_id)
        stale = await service.create(
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.INCONCLUSIVE,
            producer="test",
            producer_version="1.0",
        )
        await session.commit()

    async with session_factory() as session:
        service = _service(session, key_id)
        await service.supersede(
            evidence_result_id=stale.id,
            tenant_id=tenant_id,
            session_id=UUID(session_id),
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="test",
            producer_version="1.1",
        )
        await session.commit()

    # A second, independent attempt to supersede the now-superseded
    # `stale` row directly -- the exact race BiometricProcessor's own
    # supersede() call would hit if it lost against a concurrent winner.
    async with session_factory() as session:
        service = _service(session, key_id)
        with pytest.raises(InvalidSupersessionError):
            await service.supersede(
                evidence_result_id=stale.id,
                tenant_id=tenant_id,
                session_id=UUID(session_id),
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=EvidenceResultStatus.PASS,
                producer="test",
                producer_version="1.2",
            )


# ---------------------------------------------------------------------------
# Tenant isolation under concurrency -- BD-001 audit remediation: mirrors
# test_document_processor.py's own
# test_concurrent_cross_tenant_processing_does_not_leak_or_corrupt exactly,
# one layer up. Every repository query BiometricProcessor's stages issue
# (SqlAlchemyEvidenceRepository/SqlAlchemyEvidenceResultRepository) filters
# by tenant_id at the SQL WHERE-clause level -- the same mechanism
# DocumentProcessor already relies on, not a second implementation. This
# proves that mechanism holds for the biometric pipeline specifically,
# under genuine concurrency, rather than assuming it transfers unverified.
# ---------------------------------------------------------------------------


async def test_concurrent_cross_tenant_processing_does_not_leak_or_corrupt() -> None:
    """Races the real owner's legitimate process() call against an
    attacker's forged-tenant call for the same session_id at the same
    time. The attacker's tenant_id does not match the session's real
    owner, so every tenant-scoped lookup the attacker's call makes
    (identity-claim seed, SELFIE capture, any evidence row) returns
    nothing -- the attacker's call must complete as a harmless no-op
    while the owner's call proceeds and produces a correct, uncorrupted
    full chain, regardless of which call's transactions interleave
    first."""
    owning_tenant = f"tenant-g2-race-owner-{uuid4()}"
    attacking_tenant = f"tenant-g2-race-attacker-{uuid4()}"
    key_id = f"key-{uuid4()}"
    storage = _storage(key_id)

    async with session_factory() as session:
        session_id = await _create_session(session, owning_tenant)
        identity_claim = await _seed_identity_claim(session, owning_tenant, session_id, key_id)
        await _upload_selfie(session, owning_tenant, session_id, storage)
        await session.commit()

    class _TenantScopedReferenceResolver(ReferenceSourceResolver):
        """The real DocumentBoundReferenceResolver resolves by looking
        up THIS session's effective DOCUMENT_FIELD_EXTRACTION row
        scoped to the caller's own tenant_id -- it would never resolve
        a forged-tenant caller to another tenant's identity_claim. A
        tenant-blind _FixedReferenceSourceResolver (used elsewhere in
        this file) would misrepresent that contract here, so this
        double is tenant-aware instead."""

        async def resolve(self, *, session_id: UUID, tenant_id: str) -> ReferenceResolution:
            if tenant_id != owning_tenant:
                return _not_available()
            return _resolved(identity_claim)

    def make_processor() -> BiometricProcessor:
        return _processor(
            key_id,
            storage,
            reference_source=_TenantScopedReferenceResolver(),
            face_detector=_FixedFaceDetector(_valid_detection()),
            face_quality_assessor=_FixedFaceQualityAssessor(_valid_quality()),
            face_embedder=_FixedFaceEmbedder(_valid_embedding((1.0, 0.0, 0.0))),
        )

    import asyncio

    processor_owner, processor_attacker = make_processor(), make_processor()
    await asyncio.gather(
        processor_owner.process(session_id=UUID(session_id), tenant_id=owning_tenant),
        processor_attacker.process(session_id=UUID(session_id), tenant_id=attacking_tenant),
    )

    async with session_factory() as session:
        service = _service(session, key_id)

        # The attacker's forged tenant_id must see nothing at all --
        # no cross-tenant read leakage into any of the six role-qualified
        # face evidence types, and no cross-tenant write under it either.
        for evidence_type in (
            EvidenceResultType.FACE_DETECTION_REFERENCE,
            EvidenceResultType.FACE_QUALITY_REFERENCE,
            EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            EvidenceResultType.FACE_DETECTION_PROBE,
            EvidenceResultType.FACE_QUALITY_PROBE,
            EvidenceResultType.FACE_EMBEDDING_PROBE,
            EvidenceResultType.FACE_MATCH,
        ):
            assert (
                await service.get_effective_for_session_by_type(
                    session_id=UUID(session_id),
                    tenant_id=attacking_tenant,
                    evidence_type=evidence_type,
                )
                is None
            )

        # The owner's tenant sees a correct, complete, uncorrupted chain --
        # the concurrent forged-tenant call never raced its way into
        # observing, creating, or corrupting the owner's own rows.
        match_row = await service.get_effective_for_session_by_type(
            session_id=UUID(session_id),
            tenant_id=owning_tenant,
            evidence_type=EvidenceResultType.FACE_MATCH,
        )
        assert match_row is not None and match_row.status == EvidenceResultStatus.PASS

        effective = await service.list_effective_for_session(
            session_id=UUID(session_id), tenant_id=owning_tenant
        )
        # Exactly one effective row per face evidence type for the owner --
        # no duplication from the race.
        face_types = [
            r.evidence_type
            for r in effective
            if r.evidence_type.value.startswith("FACE_")
        ]
        assert sorted(face_types, key=lambda t: t.value) == sorted(
            {
                EvidenceResultType.FACE_DETECTION_REFERENCE,
                EvidenceResultType.FACE_QUALITY_REFERENCE,
                EvidenceResultType.FACE_EMBEDDING_REFERENCE,
                EvidenceResultType.FACE_DETECTION_PROBE,
                EvidenceResultType.FACE_QUALITY_PROBE,
                EvidenceResultType.FACE_EMBEDDING_PROBE,
                EvidenceResultType.FACE_MATCH,
            },
            key=lambda t: t.value,
        )
