"""BD-001 Slice G.2 (BD-001.7/BD-001.8): the orchestration boundary
between a resolved biometric reference/probe artifact and typed,
lineage-bearing FACE_DETECTION_*/FACE_QUALITY_*/FACE_EMBEDDING_*/
FACE_MATCH EvidenceResult rows.

Mirrors infrastructure.document.processor.SqlAlchemyDocumentProcessor's
own per-stage session/freshness/persistence discipline exactly --
`_is_reusable`/`_persist_stage` are duplicated (not imported) from that
module's own definitions, the same "don't share a cross-module
primitive without two proven-identical callers" decision already
applied throughout this project. One deliberate divergence: this
module's own `_persist_stage` RETURNS the resulting EvidenceResult
(DocumentProcessor's own version returns None) -- biometric stages
chain via each other's ids (FACE_QUALITY_REFERENCE's parent is
FACE_DETECTION_REFERENCE's own row id), which DocumentProcessor's
stages never need to do (they all chain to a shared capture_id, or
converge via independent fetches).

The reference-side and probe-side chains are deliberately two distinct
methods, not one parameterized `_process_chain(role, ...)` -- they
acquire their roots in genuinely different ways (a resolved, transient
ReferenceIdentity vs. a real, persisted SELFIE capture) and have
different non-RESOLVED-outcome semantics (BD-001.7 §3a vs. §3). They
share only the genuinely-identical low-level primitives below.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.audit.service import AuditService
from core.evidence.enums import EvidenceType
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult, ModelReference
from core.evidence_result.service import EvidenceResultService
from core.face.capabilities import (
    CapabilityUnavailableError,
    FaceDetector,
    FaceEmbedder,
    FaceQualityAssessor,
)
from core.face.matcher import FaceMatcher
from core.face.reason_codes import FaceReasonCode
from core.face.reference import (
    ReferenceAcquisitionOutcome,
    ReferenceArtifactImage,
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
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository

if TYPE_CHECKING:
    from core.security.keys import KeyProvider
    from infrastructure.storage.interface import ObjectStorage

_PRODUCER = "biometric-processor"
_PRODUCER_VERSION = "1.0"


def _is_reusable(status: EvidenceResultStatus) -> bool:
    """Byte-for-byte the same predicate as
    infrastructure.document.processor._is_reusable: PASS/FAIL/
    INCONCLUSIVE are terminal; UNAVAILABLE is retryable."""
    return status is not EvidenceResultStatus.UNAVAILABLE


def _detection_outcome_mapping(
    detection: FaceDetection,
) -> tuple[EvidenceResultStatus, tuple[str, ...], dict[str, Any] | None]:
    """BD-001.8 §7. face_count==0/2+ under outcome=VALID are diagnosable
    pipeline facts with no corresponding FaceDetectionOutcome member --
    DETECTION_NO_FACE/DETECTION_AMBIGUOUS exist at this mapping layer
    only, never as domain-type members."""
    if detection.outcome is FaceDetectionOutcome.UNREADABLE:
        return EvidenceResultStatus.INCONCLUSIVE, (FaceReasonCode.DETECTION_UNREADABLE.value,), None
    assert (
        detection.face_count is not None
    )  # VALID implies populated, per FaceDetection's own contract
    if detection.face_count == 0:
        return EvidenceResultStatus.INCONCLUSIVE, (FaceReasonCode.DETECTION_NO_FACE.value,), None
    if detection.face_count >= 2:
        return EvidenceResultStatus.INCONCLUSIVE, (FaceReasonCode.DETECTION_AMBIGUOUS.value,), None
    return EvidenceResultStatus.PASS, (), {"detected": True, "face_count": 1}


_QUALITY_OUTCOME_MAP: dict[
    FaceQualityOutcome, tuple[EvidenceResultStatus, FaceReasonCode | None]
] = {
    FaceQualityOutcome.UNREADABLE: (
        EvidenceResultStatus.INCONCLUSIVE,
        FaceReasonCode.QUALITY_UNREADABLE,
    ),
    FaceQualityOutcome.NO_FACE: (EvidenceResultStatus.INCONCLUSIVE, FaceReasonCode.QUALITY_NO_FACE),
    FaceQualityOutcome.AMBIGUOUS: (
        EvidenceResultStatus.INCONCLUSIVE,
        FaceReasonCode.QUALITY_AMBIGUOUS,
    ),
    FaceQualityOutcome.VALID: (EvidenceResultStatus.PASS, None),
}


def _quality_outcome_mapping(
    quality: FaceQuality,
) -> tuple[EvidenceResultStatus, tuple[str, ...], dict[str, Any] | None, float | None]:
    """BD-001.8 §7. score is threaded as its own return value -- a
    top-level EvidenceResult field, mirroring DocumentProcessor's own
    _run_quality precedent, never duplicated inside result."""
    status, reason = _QUALITY_OUTCOME_MAP[quality.outcome]
    reason_codes = (reason.value,) if reason is not None else ()
    if quality.outcome is FaceQualityOutcome.VALID:
        return status, reason_codes, {"quality_score": quality.quality_score}, quality.quality_score
    return status, reason_codes, None, None


_EMBEDDING_OUTCOME_MAP: dict[
    FaceEmbeddingOutcome, tuple[EvidenceResultStatus, FaceReasonCode | None]
] = {
    FaceEmbeddingOutcome.UNREADABLE: (
        EvidenceResultStatus.INCONCLUSIVE,
        FaceReasonCode.EMBEDDING_UNREADABLE,
    ),
    FaceEmbeddingOutcome.NO_FACE: (
        EvidenceResultStatus.INCONCLUSIVE,
        FaceReasonCode.EMBEDDING_NO_FACE,
    ),
    FaceEmbeddingOutcome.AMBIGUOUS: (
        EvidenceResultStatus.INCONCLUSIVE,
        FaceReasonCode.EMBEDDING_AMBIGUOUS,
    ),
    FaceEmbeddingOutcome.VALID: (EvidenceResultStatus.PASS, None),
}


def _embedding_outcome_mapping(
    embedding: FaceEmbedding,
) -> tuple[EvidenceResultStatus, tuple[str, ...], dict[str, Any] | None, ModelReference | None]:
    status, reason = _EMBEDDING_OUTCOME_MAP[embedding.outcome]
    reason_codes = (reason.value,) if reason is not None else ()
    if embedding.outcome is FaceEmbeddingOutcome.VALID:
        assert embedding.embedding is not None and embedding.embedding_dimensions is not None
        result = {
            "embedding": list(embedding.embedding),
            "embedding_dimensions": embedding.embedding_dimensions,
        }
        return status, reason_codes, result, embedding.model_reference
    return status, reason_codes, None, None


def _row_to_face_embedding(row: EvidenceResult) -> FaceEmbedding:
    """Rebuilds the domain value FaceMatcher.compare() needs from a
    persisted, lineage-current, PASS FACE_EMBEDDING_REFERENCE/PROBE
    row -- the only place this module reconstructs a domain value from
    persisted state (BD-001.8 §8)."""
    assert row.result is not None
    embedding = tuple(row.result["embedding"])
    return FaceEmbedding(
        outcome=FaceEmbeddingOutcome.VALID,
        embedding=embedding,
        embedding_dimensions=row.result["embedding_dimensions"],
        model_reference=row.model_reference,
    )


def _lineage_is_current(
    detection: EvidenceResult | None,
    quality: EvidenceResult | None,
    embedding: EvidenceResult | None,
) -> bool:
    """BD-001.8 §8, the fix for the lineage gap: an effective PASS
    embedding is usable only when its complete upstream lineage is
    ALSO current -- never "effective and PASS" alone. Pure row
    arithmetic over three already-fetched rows, with no knowledge of
    ReferenceIdentity/SELFIE at all -- this is what makes it safe to
    share between the reference and probe sides (BD-001.7 §3a's own
    "no synthetic downstream rows" principle means a stale chain is
    never cleaned up; this check is what makes leaving it uncleaned up
    safe)."""
    if embedding is None or embedding.status is not EvidenceResultStatus.PASS:
        return False
    if quality is None or embedding.parent_evidence_result_ids != (quality.id,):
        return False
    if detection is None or quality.parent_evidence_result_ids != (detection.id,):
        return False
    return detection.status is EvidenceResultStatus.PASS


class BiometricProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: "KeyProvider",
        key_id: str,
        storage: "ObjectStorage",
        face_detector: FaceDetector,
        face_quality_assessor: FaceQualityAssessor,
        face_embedder: FaceEmbedder,
        face_matcher: FaceMatcher,
        reference_source: ReferenceSourceResolver,
    ) -> None:
        self._session_factory = session_factory
        self._key_provider = key_provider
        self._key_id = key_id
        self._storage = storage
        self._face_detector = face_detector
        self._face_quality_assessor = face_quality_assessor
        self._face_embedder = face_embedder
        self._face_matcher = face_matcher
        self._reference_source = reference_source

    async def process(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Three sequential top-level steps, mirroring
        DocumentProcessor.process()'s own shape -- none gated on
        another's success (BD-001.7 G.2-10's "invocation unconditional"
        principle). Any exception from any step propagates uncaught;
        no later step runs after an earlier one fails this same
        invocation."""
        await self._run_reference_chain(session_id, tenant_id, request_id, correlation_id)
        await self._run_probe_chain(session_id, tenant_id, request_id, correlation_id)
        await self._run_face_match(session_id, tenant_id, request_id, correlation_id)

    def _build_service(self, session: AsyncSession) -> EvidenceResultService:
        return EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, self._key_provider, self._key_id),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )

    @staticmethod
    async def _persist_stage(
        service: EvidenceResultService,
        existing: EvidenceResult | None,
        *,
        session_id: UUID,
        tenant_id: str,
        evidence_type: EvidenceResultType,
        status: EvidenceResultStatus,
        request_id: str | None,
        correlation_id: str | None,
        parent_evidence_result_ids: tuple[UUID, ...] = (),
        source_reference: UUID | None = None,
        result: dict[str, Any] | None = None,
        score: float | None = None,
        model_reference: ModelReference | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> EvidenceResult:
        """Same create()-vs-supersede() branching as
        infrastructure.document.processor's own _persist_stage.
        Deliberately RETURNS the resulting row (that module's own
        version returns None) -- see this module's own docstring.

        `source_reference` links a row directly to a raw Evidence
        capture (validated against the Evidence repository) -- a
        completely different id space from `parent_evidence_result_ids`
        (validated against the EvidenceResult repository). Only the
        probe side's detection stage ever sets it (the reference side
        has no raw Evidence capture to cite -- its bytes are transient,
        never a stored Evidence row). Mirrors
        infrastructure.document.processor's own supersede() call
        exactly: supersede() has no source_reference parameter at all
        -- a superseded row's lineage back to the capture remains
        reconstructable by walking supersedes_id to the original
        create()-produced row."""
        if existing is None:
            return await service.create(
                tenant_id=tenant_id,
                session_id=session_id,
                evidence_type=evidence_type,
                status=status,
                producer=_PRODUCER,
                producer_version=_PRODUCER_VERSION,
                result=result,
                score=score,
                model_reference=model_reference,
                reason_codes=reason_codes,
                source_reference=source_reference,
                parent_evidence_result_ids=parent_evidence_result_ids,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        return await service.supersede(
            evidence_result_id=existing.id,
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=evidence_type,
            status=status,
            producer=_PRODUCER,
            producer_version=_PRODUCER_VERSION,
            result=result,
            score=score,
            model_reference=model_reference,
            reason_codes=reason_codes,
            parent_evidence_result_ids=parent_evidence_result_ids,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def _run_detection_stage(
        self,
        *,
        evidence_type: EvidenceResultType,
        parent_evidence_result_ids: tuple[UUID, ...] = (),
        source_reference: UUID | None = None,
        image: bytes,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> EvidenceResult:
        """The one stage that may be anchored either to an
        EvidenceResult parent (reference side: identity_claim) or a raw
        Evidence capture (probe side: the SELFIE capture itself) --
        exactly one of parent_evidence_result_ids/source_reference is
        ever non-empty/non-None for a given call, never both."""
        async with self._session_factory() as session:
            service = self._build_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
            )
            if (
                existing is not None
                and _is_reusable(existing.status)
                and existing.parent_evidence_result_ids == parent_evidence_result_ids
                and existing.source_reference == source_reference
            ):
                return existing

            try:
                detection = await self._face_detector.detect(image)
            except CapabilityUnavailableError as exc:
                row = await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=evidence_type,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    parent_evidence_result_ids=parent_evidence_result_ids,
                    source_reference=source_reference,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return row

            status, reason_codes, result = _detection_outcome_mapping(detection)
            row = await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
                status=status,
                reason_codes=reason_codes,
                result=result,
                parent_evidence_result_ids=parent_evidence_result_ids,
                source_reference=source_reference,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()
            return row

    async def _run_quality_stage(
        self,
        *,
        evidence_type: EvidenceResultType,
        parent_evidence_result_ids: tuple[UUID, ...],
        image: bytes,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> EvidenceResult:
        async with self._session_factory() as session:
            service = self._build_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
            )
            if (
                existing is not None
                and _is_reusable(existing.status)
                and existing.parent_evidence_result_ids == parent_evidence_result_ids
            ):
                return existing

            try:
                quality = await self._face_quality_assessor.assess(image)
            except CapabilityUnavailableError as exc:
                row = await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=evidence_type,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    parent_evidence_result_ids=parent_evidence_result_ids,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return row

            status, reason_codes, result, score = _quality_outcome_mapping(quality)
            row = await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
                status=status,
                reason_codes=reason_codes,
                result=result,
                score=score,
                parent_evidence_result_ids=parent_evidence_result_ids,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()
            return row

    async def _run_embedding_stage(
        self,
        *,
        evidence_type: EvidenceResultType,
        parent_evidence_result_ids: tuple[UUID, ...],
        image: bytes,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> EvidenceResult:
        async with self._session_factory() as session:
            service = self._build_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
            )
            if (
                existing is not None
                and _is_reusable(existing.status)
                and existing.parent_evidence_result_ids == parent_evidence_result_ids
            ):
                return existing

            try:
                embedding = await self._face_embedder.embed(image)
            except CapabilityUnavailableError as exc:
                row = await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=evidence_type,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    parent_evidence_result_ids=parent_evidence_result_ids,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return row

            status, reason_codes, result, model_reference = _embedding_outcome_mapping(embedding)
            row = await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
                status=status,
                reason_codes=reason_codes,
                result=result,
                model_reference=model_reference,
                parent_evidence_result_ids=parent_evidence_result_ids,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()
            return row

    async def _persist_reference_acquisition_failure(
        self,
        session_id: UUID,
        tenant_id: str,
        reason: FaceReasonCode,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        """BD-001.7 §3a (G.2-S11): NO_FACE_FOUND/AMBIGUOUS from
        ReferenceSourceResolver.resolve() persist directly on
        FACE_DETECTION_REFERENCE -- no capability call, no parent (the
        document itself was never usably resolved, so there is nothing
        legitimate to cite as lineage)."""
        async with self._session_factory() as session:
            service = self._build_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
            )
            if (
                existing is not None
                and existing.status is EvidenceResultStatus.INCONCLUSIVE
                and existing.reason_codes == (reason.value,)
            ):
                return  # already reflects this exact state
            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
                status=EvidenceResultStatus.INCONCLUSIVE,
                reason_codes=(reason.value,),
                parent_evidence_result_ids=(),
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()

    async def _persist_ambiguous_selfie(
        self,
        evidence_type: EvidenceResultType,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        """BD-001.7 §3 (G.2-S1): 2+ effective SELFIE captures -- applied
        identically across all three probe stages."""
        async with self._session_factory() as session:
            service = self._build_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
            )
            if (
                existing is not None
                and existing.status is EvidenceResultStatus.INCONCLUSIVE
                and existing.reason_codes == (FaceReasonCode.AMBIGUOUS_SELFIE_CAPTURE.value,)
            ):
                return
            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=evidence_type,
                status=EvidenceResultStatus.INCONCLUSIVE,
                reason_codes=(FaceReasonCode.AMBIGUOUS_SELFIE_CAPTURE.value,),
                parent_evidence_result_ids=(),
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()

    async def _run_reference_chain(
        self,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        resolution = await self._reference_source.resolve(
            session_id=session_id, tenant_id=tenant_id
        )
        # CapabilityUnavailableError propagates uncaught (BD-001.2 D-3 /
        # BD-001.7 G.2-10) -- no try/except around resolve() here.

        if resolution.outcome is ReferenceAcquisitionOutcome.NOT_AVAILABLE:
            return  # G.2-S11: silent no-op, no row

        if resolution.outcome in (
            ReferenceAcquisitionOutcome.NO_FACE_FOUND,
            ReferenceAcquisitionOutcome.AMBIGUOUS,
        ):
            reason = (
                FaceReasonCode.REFERENCE_NO_FACE_FOUND
                if resolution.outcome is ReferenceAcquisitionOutcome.NO_FACE_FOUND
                else FaceReasonCode.REFERENCE_AMBIGUOUS
            )
            await self._persist_reference_acquisition_failure(
                session_id, tenant_id, reason, request_id, correlation_id
            )
            return
            # G.2-S11: chain terminates at FACE_DETECTION_REFERENCE.
            # Deliberately does not touch any existing FACE_QUALITY_
            # REFERENCE/FACE_EMBEDDING_REFERENCE row -- BD-001.8 §9:
            # correctness lives in _lineage_is_current, never in a
            # cleanup pass here.

        assert resolution.outcome is ReferenceAcquisitionOutcome.RESOLVED
        identity = resolution.identity
        assert identity is not None

        if not isinstance(identity.reference_artifact, ReferenceArtifactImage):
            raise NotImplementedError(
                "ReferenceArtifactEmbedding is out of scope for this demo (BP-001 §6c OPEN)"
            )

        image = identity.reference_artifact.image
        detection_row = await self._run_detection_stage(
            evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
            parent_evidence_result_ids=(identity.identity_claim,),
            image=image,
            session_id=session_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        if detection_row.status is not EvidenceResultStatus.PASS:
            return

        quality_row = await self._run_quality_stage(
            evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
            parent_evidence_result_ids=(detection_row.id,),
            image=image,
            session_id=session_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        # BD-001 Slice C's own frozen "no gating" decision: proceed to
        # embedding regardless of quality_row.status.

        await self._run_embedding_stage(
            evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            parent_evidence_result_ids=(quality_row.id,),
            image=image,
            session_id=session_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def _run_probe_chain(
        self,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            captures = [
                e
                for e in await SqlAlchemyEvidenceRepository(session).list_for_session(
                    session_id, tenant_id
                )
                if e.evidence_type is EvidenceType.SELFIE
            ]
        if len(captures) == 0:
            return  # G.2-S1: silent no-op

        if len(captures) > 1:
            for evidence_type in (
                EvidenceResultType.FACE_DETECTION_PROBE,
                EvidenceResultType.FACE_QUALITY_PROBE,
                EvidenceResultType.FACE_EMBEDDING_PROBE,
            ):
                await self._persist_ambiguous_selfie(
                    evidence_type, session_id, tenant_id, request_id, correlation_id
                )
            return  # G.2-S1: no selection, ever

        capture = captures[0]
        image = await self._storage.get(capture.object_key)

        detection_row = await self._run_detection_stage(
            evidence_type=EvidenceResultType.FACE_DETECTION_PROBE,
            source_reference=capture.id,
            image=image,
            session_id=session_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        if detection_row.status is not EvidenceResultStatus.PASS:
            return

        quality_row = await self._run_quality_stage(
            evidence_type=EvidenceResultType.FACE_QUALITY_PROBE,
            parent_evidence_result_ids=(detection_row.id,),
            image=image,
            session_id=session_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

        await self._run_embedding_stage(
            evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
            parent_evidence_result_ids=(quality_row.id,),
            image=image,
            session_id=session_id,
            tenant_id=tenant_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def _run_face_match(
        self,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            service = self._build_service(session)
            # G.2-4: fresh re-read, never trusting the reference/probe
            # walks' own return values from earlier in this invocation.
            reference_detection = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_DETECTION_REFERENCE,
            )
            reference_quality = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_QUALITY_REFERENCE,
            )
            reference_embedding = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_EMBEDDING_REFERENCE,
            )
            probe_detection = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_DETECTION_PROBE,
            )
            probe_quality = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_QUALITY_PROBE,
            )
            probe_embedding = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_EMBEDDING_PROBE,
            )
            existing_match = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_MATCH,
            )

            reference_usable = _lineage_is_current(
                reference_detection, reference_quality, reference_embedding
            )
            probe_usable = _lineage_is_current(probe_detection, probe_quality, probe_embedding)

            if not (reference_usable and probe_usable):
                if existing_match is not None:
                    current_parents = tuple(
                        row.id
                        for row, usable in (
                            (reference_embedding, reference_usable),
                            (probe_embedding, probe_usable),
                        )
                        if usable and row is not None
                    )
                    if existing_match.parent_evidence_result_ids != current_parents:
                        await self._persist_stage(
                            service,
                            existing_match,
                            session_id=session_id,
                            tenant_id=tenant_id,
                            evidence_type=EvidenceResultType.FACE_MATCH,
                            status=EvidenceResultStatus.INCONCLUSIVE,
                            reason_codes=(FaceReasonCode.PARENT_EVIDENCE_NOT_USABLE.value,),
                            result=None,
                            parent_evidence_result_ids=current_parents,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                        await session.commit()
                return  # G.2-4: "no row until both ready" when nothing existed to invalidate

            assert reference_embedding is not None and probe_embedding is not None
            current_parents = (reference_embedding.id, probe_embedding.id)
            if (
                existing_match is not None
                and _is_reusable(existing_match.status)
                and existing_match.parent_evidence_result_ids == current_parents
            ):
                return  # G.2-5: fresh, reusable

            reference_domain = _row_to_face_embedding(reference_embedding)
            probe_domain = _row_to_face_embedding(probe_embedding)
            outcome = self._face_matcher.compare(reference=reference_domain, probe=probe_domain)

            if outcome.compatible:
                status = EvidenceResultStatus.PASS
                reason_codes: tuple[str, ...] = ()
                result: dict[str, Any] | None = {
                    "similarity": outcome.similarity,
                    "reference_evidence_result_id": str(reference_embedding.id),
                    "probe_evidence_result_id": str(probe_embedding.id),
                }
            else:
                # BD-001 Slice E, restated not reopened (BD-001.7 §8).
                status = EvidenceResultStatus.INCONCLUSIVE
                reason_codes = (FaceReasonCode.REPRESENTATION_INCOMPATIBLE.value,)
                result = None

            await self._persist_stage(
                service,
                existing_match,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.FACE_MATCH,
                status=status,
                reason_codes=reason_codes,
                result=result,
                parent_evidence_result_ids=current_parents,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()
