"""Concrete implementation of core.document.processor's DocumentProcessor
Protocol (DP-001 Decisions 3/4, DP-002 Phase 1).

Each stage runs in its own freshly-opened session and commits
independently (DP-001 Decision 4's explicit implementation note) -- the
mechanism that makes partial-stage-failure preservation true at the
database level, not just the application level. Stages run sequentially,
not via asyncio.gather(): Decision 4 permits ("MAY"), not requires,
concurrent execution of independent stages, and a connection pool that
can only serve one real connection at a time -- the single-connection
StaticPool this project's SQLite test fixture deliberately uses, so its
in-memory database stays shared across every session in a test -- cannot
safely serve two concurrently-open independent sessions at once
(confirmed live as a genuine deadlock during Phase 1 implementation, not
assumed). Same dependency-inversion shape as
infrastructure.deletion.reconciliation's reconciler classes: core/
depends only on the narrow Protocol, never on SQLAlchemy.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.audit.service import AuditService
from core.document.capabilities import (
    BarcodeDecoder,
    CapabilityUnavailableError,
    DocumentClassifier,
    MRZParser,
    OCREngine,
    QualityAssessor,
)
from core.document.reason_codes import DocumentReasonCode
from core.document.types import BarcodeReadOutcome, MRZReadOutcome, OCRReadOutcome
from core.evidence.enums import EvidenceType
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult
from core.evidence_result.service import EvidenceResultService
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository

if TYPE_CHECKING:
    from core.security.keys import KeyProvider
    from infrastructure.storage.interface import ObjectStorage

_PRODUCER_QUALITY = "document-quality-assessor-deterministic"
_PRODUCER_CLASSIFIER = "document-classifier-deterministic"
_PRODUCER_MRZ = "document-mrz-parser-deterministic"
_PRODUCER_BARCODE = "document-barcode-decoder-deterministic"
_PRODUCER_OCR = "document-ocr-engine-deterministic"
_PRODUCER_VERSION = "1.0"

# DP-003 §7's frozen MRZ/Barcode failure-mapping table, encoded directly
# -- an exhaustiveness test iterates each outcome enum's members and
# asserts every one has an entry here, so a future new outcome member
# can't silently fall through un-mapped.
_MRZ_OUTCOME_MAP: dict[MRZReadOutcome, tuple[EvidenceResultStatus, str | None]] = {
    MRZReadOutcome.UNREADABLE: (
        EvidenceResultStatus.INCONCLUSIVE,
        DocumentReasonCode.MRZ_UNREADABLE.value,
    ),
    MRZReadOutcome.MALFORMED: (
        EvidenceResultStatus.INCONCLUSIVE,
        DocumentReasonCode.MRZ_MALFORMED.value,
    ),
    MRZReadOutcome.CHECK_DIGIT_MISMATCH: (
        EvidenceResultStatus.FAIL,
        DocumentReasonCode.MRZ_CHECK_DIGIT_MISMATCH.value,
    ),
    MRZReadOutcome.VALID: (EvidenceResultStatus.PASS, None),
}

# No EvidenceResultStatus.FAIL value anywhere in this map -- BarcodeReadOutcome
# has no member corresponding to one (DP-003 Decision 2), so there is no
# code path, not merely a convention, by which BARCODE_QR could reach FAIL.
_BARCODE_OUTCOME_MAP: dict[BarcodeReadOutcome, tuple[EvidenceResultStatus, str | None]] = {
    BarcodeReadOutcome.UNREADABLE: (
        EvidenceResultStatus.INCONCLUSIVE,
        DocumentReasonCode.BARCODE_UNREADABLE.value,
    ),
    BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED: (
        EvidenceResultStatus.INCONCLUSIVE,
        DocumentReasonCode.BARCODE_PAYLOAD_UNRECOGNIZED.value,
    ),
    BarcodeReadOutcome.PAYLOAD_MALFORMED: (
        EvidenceResultStatus.INCONCLUSIVE,
        DocumentReasonCode.BARCODE_PAYLOAD_MALFORMED.value,
    ),
    BarcodeReadOutcome.VALID: (EvidenceResultStatus.PASS, None),
}

# DP-005 §7's frozen OCR failure-mapping table. No UNREADABLE/NOT_SUBMITTED
# split exists here the way MRZ/Barcode's maps have one -- OCR has no
# NOT_SUBMITTED outcome at all (DP-005 Decision 3), so this map only ever
# needs to cover OCRReadOutcome's two members. No FAIL entry either, for
# the same structural reason as _BARCODE_OUTCOME_MAP (DP-005 Decision 2).
_OCR_OUTCOME_MAP: dict[OCRReadOutcome, tuple[EvidenceResultStatus, str | None]] = {
    OCRReadOutcome.UNREADABLE: (
        EvidenceResultStatus.INCONCLUSIVE,
        DocumentReasonCode.OCR_UNREADABLE.value,
    ),
    OCRReadOutcome.VALID: (EvidenceResultStatus.PASS, None),
}

# A policy-agnostic midpoint DocumentProcessor applies to map a
# capability's raw score to PASS/FAIL -- decoupled from however a given
# QualityAssessor implementation computes its score (EVD-3.12.3: quality
# thresholds used for decisioning must be defined by policy or component
# semantics, not undocumented constants buried in the capability itself).
_QUALITY_PASS_THRESHOLD = 0.5


def _is_reusable(status: EvidenceResultStatus) -> bool:
    """DP-002's Phase-1-scoped instance of DP-001's carried-forward
    reusable-vs-retryable matrix: PASS/FAIL/INCONCLUSIVE are terminal for
    these two deterministic capabilities; UNAVAILABLE is retryable. The
    full general matrix (which statuses are retryable-with-a-budget,
    etc.) remains an open item for Phase 2+."""
    return status is not EvidenceResultStatus.UNAVAILABLE


class SqlAlchemyDocumentProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: "KeyProvider",
        key_id: str,
        storage: "ObjectStorage",
        quality_assessor: QualityAssessor,
        document_classifier: DocumentClassifier,
        mrz_parser: MRZParser,
        barcode_decoder: BarcodeDecoder,
        ocr_engine: OCREngine,
    ) -> None:
        self._session_factory = session_factory
        self._key_provider = key_provider
        self._key_id = key_id
        self._storage = storage
        self._quality_assessor = quality_assessor
        self._document_classifier = document_classifier
        self._mrz_parser = mrz_parser
        self._barcode_decoder = barcode_decoder
        self._ocr_engine = ocr_engine

    async def process(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            evidence_repository = SqlAlchemyEvidenceRepository(session)
            captures = [
                evidence
                for evidence in await evidence_repository.list_for_session(session_id, tenant_id)
                if evidence.evidence_type is EvidenceType.DOCUMENT
            ]

        if not captures:
            # Absence is the Decision Engine's concern (REQUIRED_EVIDENCE_MISSING
            # via policy evaluation), not this method's -- DP-002 §4.
            return

        ambiguous = len(captures) > 1
        capture_id = captures[0].id if not ambiguous else None
        object_key = captures[0].object_key if not ambiguous else None

        # DP-001 Decision 4 permits ("MAY"), not requires, concurrent
        # execution of independent first-order stages -- run sequentially
        # here rather than via asyncio.gather(). A connection pool that
        # can only ever hand out one real connection at a time (the
        # single-connection StaticPool this project's SQLite test fixture
        # deliberately uses, so its in-memory database stays shared
        # across every session in a test) cannot safely serve two
        # concurrently-open independent sessions at once -- confirmed
        # live as a genuine deadlock, not assumed. Real Postgres has no
        # such constraint; nothing about this ordering is Postgres-
        # specific, it is simply the more conservative, universally-safe
        # choice Decision 4's "MAY" leaves available. Each stage still
        # gets its own independent session and commits independently,
        # preserving partial-stage-failure preservation regardless of
        # ordering.
        await self._run_quality(
            session_id=session_id,
            tenant_id=tenant_id,
            capture_id=capture_id,
            object_key=object_key,
            ambiguous=ambiguous,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await self._run_classification(
            session_id=session_id,
            tenant_id=tenant_id,
            capture_id=capture_id,
            object_key=object_key,
            ambiguous=ambiguous,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        # DP-003 Decision 7: invoked unconditionally, identically to the
        # two stages above -- no branching on DOCUMENT_CLASSIFICATION's
        # result to skip MRZ/Barcode for document types not expected to
        # carry them. NOT_SUBMITTED absorbs "no applicable zone/symbol
        # found" regardless of document type; any different evidentiary
        # weight is a policy concern, not evidence-producer logic.
        await self._run_mrz(
            session_id=session_id,
            tenant_id=tenant_id,
            capture_id=capture_id,
            object_key=object_key,
            ambiguous=ambiguous,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await self._run_barcode(
            session_id=session_id,
            tenant_id=tenant_id,
            capture_id=capture_id,
            object_key=object_key,
            ambiguous=ambiguous,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        # DP-005 Decision 3: invoked unconditionally, like every stage
        # above -- OCR has no capability-level absence state (a document
        # image is inherently an OCR input, unlike an MRZ zone or barcode
        # symbol that may genuinely be physically absent). The shared
        # ambiguous-capture precondition below still short-circuits
        # BEFORE OCREngine.extract() is ever called, exactly as it does
        # for every other stage -- that pipeline-level precondition is
        # unrelated to, and unaffected by, Decision 3.
        await self._run_ocr(
            session_id=session_id,
            tenant_id=tenant_id,
            capture_id=capture_id,
            object_key=object_key,
            ambiguous=ambiguous,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _build_evidence_result_service(self, session: AsyncSession) -> EvidenceResultService:
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
        producer: str,
        request_id: str | None,
        correlation_id: str | None,
        source_reference: UUID | None = None,
        parent_evidence_result_ids: tuple[UUID, ...] = (),
        result: dict[str, Any] | None = None,
        score: float | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        """DP-001 Decision 4: a retry supersedes the prior attempt rather
        than creating a second effective result. supersede() (unlike
        create()) has no source_reference parameter -- a superseded row's
        lineage back to the capture remains reconstructable by walking
        supersedes_id to the original create()-produced row, which always
        carries it (a stage's very first attempt is always a create(),
        since there is nothing yet to supersede).

        `parent_evidence_result_ids` DOES need to be threaded on every
        attempt, including supersede() (DP-009 §6) -- unlike
        source_reference, a derived stage's parent set can itself change
        between attempts (DOCUMENT_FIELD_EXTRACTION's own freshness
        principle, DP-008 §4), so it is never safe to assume a
        superseding row's lineage is reconstructable from the original
        attempt's."""
        if existing is None:
            await service.create(
                tenant_id=tenant_id,
                session_id=session_id,
                evidence_type=evidence_type,
                status=status,
                producer=producer,
                producer_version=_PRODUCER_VERSION,
                result=result,
                score=score,
                reason_codes=reason_codes,
                source_reference=source_reference,
                parent_evidence_result_ids=parent_evidence_result_ids,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        else:
            await service.supersede(
                evidence_result_id=existing.id,
                tenant_id=tenant_id,
                session_id=session_id,
                evidence_type=evidence_type,
                status=status,
                producer=producer,
                producer_version=_PRODUCER_VERSION,
                result=result,
                score=score,
                reason_codes=reason_codes,
                parent_evidence_result_ids=parent_evidence_result_ids,
                request_id=request_id,
                correlation_id=correlation_id,
            )

    async def _run_quality(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        capture_id: UUID | None,
        object_key: str | None,
        ambiguous: bool,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            service = self._build_evidence_result_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
            )
            if existing is not None and _is_reusable(existing.status):
                return

            if ambiguous:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
                    status=EvidenceResultStatus.INCONCLUSIVE,
                    reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                    producer=_PRODUCER_QUALITY,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            assert object_key is not None and capture_id is not None  # ambiguous handled above
            image = await self._storage.get(object_key)
            try:
                assessment = await self._quality_assessor.assess(image)
            except CapabilityUnavailableError as exc:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    producer=_PRODUCER_QUALITY,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            passed = assessment.quality_score >= _QUALITY_PASS_THRESHOLD
            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_QUALITY,
                status=EvidenceResultStatus.PASS if passed else EvidenceResultStatus.FAIL,
                result={"quality_score": assessment.quality_score},
                score=assessment.quality_score,
                reason_codes=() if passed else (DocumentReasonCode.IMAGE_TOO_BLURRY.value,),
                producer=_PRODUCER_QUALITY,
                source_reference=capture_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()

    async def _run_classification(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        capture_id: UUID | None,
        object_key: str | None,
        ambiguous: bool,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            service = self._build_evidence_result_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_CLASSIFICATION,
            )
            if existing is not None and _is_reusable(existing.status):
                return

            if ambiguous:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.DOCUMENT_CLASSIFICATION,
                    status=EvidenceResultStatus.INCONCLUSIVE,
                    reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                    producer=_PRODUCER_CLASSIFIER,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            assert object_key is not None and capture_id is not None  # ambiguous handled above
            image = await self._storage.get(object_key)
            try:
                classification = await self._document_classifier.classify(image)
            except CapabilityUnavailableError as exc:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.DOCUMENT_CLASSIFICATION,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    producer=_PRODUCER_CLASSIFIER,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            if classification.document_type is None:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.DOCUMENT_CLASSIFICATION,
                    status=EvidenceResultStatus.FAIL,
                    reason_codes=(DocumentReasonCode.DOCUMENT_UNSUPPORTED.value,),
                    producer=_PRODUCER_CLASSIFIER,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_CLASSIFICATION,
                status=EvidenceResultStatus.PASS,
                result={"document_type": classification.document_type.value},
                score=classification.confidence,
                producer=_PRODUCER_CLASSIFIER,
                source_reference=capture_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()

    async def _run_mrz(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        capture_id: UUID | None,
        object_key: str | None,
        ambiguous: bool,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            service = self._build_evidence_result_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.MRZ,
            )
            if existing is not None and _is_reusable(existing.status):
                return

            if ambiguous:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.MRZ,
                    status=EvidenceResultStatus.INCONCLUSIVE,
                    reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                    producer=_PRODUCER_MRZ,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            assert object_key is not None and capture_id is not None  # ambiguous handled above
            image = await self._storage.get(object_key)
            try:
                read_result = await self._mrz_parser.parse(image)
            except CapabilityUnavailableError as exc:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.MRZ,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    producer=_PRODUCER_MRZ,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            if read_result is None:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.MRZ,
                    status=EvidenceResultStatus.NOT_SUBMITTED,
                    producer=_PRODUCER_MRZ,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            status, reason_code = _MRZ_OUTCOME_MAP[read_result.outcome]
            result_payload = (
                {"raw": read_result.extraction.raw, "fields": read_result.extraction.fields}
                if read_result.extraction is not None
                else None
            )
            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.MRZ,
                status=status,
                reason_codes=(reason_code,) if reason_code else (),
                result=result_payload,
                producer=_PRODUCER_MRZ,
                source_reference=capture_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()

    async def _run_barcode(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        capture_id: UUID | None,
        object_key: str | None,
        ambiguous: bool,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            service = self._build_evidence_result_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.BARCODE_QR,
            )
            if existing is not None and _is_reusable(existing.status):
                return

            if ambiguous:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.BARCODE_QR,
                    status=EvidenceResultStatus.INCONCLUSIVE,
                    reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                    producer=_PRODUCER_BARCODE,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            assert object_key is not None and capture_id is not None  # ambiguous handled above
            image = await self._storage.get(object_key)
            try:
                read_result = await self._barcode_decoder.decode(image)
            except CapabilityUnavailableError as exc:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.BARCODE_QR,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    producer=_PRODUCER_BARCODE,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            if read_result is None:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.BARCODE_QR,
                    status=EvidenceResultStatus.NOT_SUBMITTED,
                    producer=_PRODUCER_BARCODE,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            status, reason_code = _BARCODE_OUTCOME_MAP[read_result.outcome]
            result_payload = (
                {
                    "raw": read_result.extraction.raw,
                    "fields": read_result.extraction.fields,
                    "symbology": read_result.extraction.symbology,
                }
                if read_result.extraction is not None
                else None
            )
            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.BARCODE_QR,
                status=status,
                reason_codes=(reason_code,) if reason_code else (),
                result=result_payload,
                producer=_PRODUCER_BARCODE,
                source_reference=capture_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()

    async def _run_ocr(
        self,
        *,
        session_id: UUID,
        tenant_id: str,
        capture_id: UUID | None,
        object_key: str | None,
        ambiguous: bool,
        request_id: str | None,
        correlation_id: str | None,
    ) -> None:
        async with self._session_factory() as session:
            service = self._build_evidence_result_service(session)
            existing = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.OCR_EXTRACTION,
            )
            if existing is not None and _is_reusable(existing.status):
                return

            if ambiguous:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.OCR_EXTRACTION,
                    status=EvidenceResultStatus.INCONCLUSIVE,
                    reason_codes=(DocumentReasonCode.AMBIGUOUS_DOCUMENT_CAPTURE.value,),
                    producer=_PRODUCER_OCR,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            assert object_key is not None and capture_id is not None  # ambiguous handled above
            image = await self._storage.get(object_key)
            try:
                read_result = await self._ocr_engine.extract(image)
            except CapabilityUnavailableError as exc:
                await self._persist_stage(
                    service,
                    existing,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    evidence_type=EvidenceResultType.OCR_EXTRACTION,
                    status=EvidenceResultStatus.UNAVAILABLE,
                    reason_codes=(exc.reason_code,),
                    producer=_PRODUCER_OCR,
                    source_reference=capture_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                await session.commit()
                return

            # No `if read_result is None` branch here -- unlike MRZ/Barcode,
            # OCREngine.extract() never returns None (DP-005 Decision 3).
            status, reason_code = _OCR_OUTCOME_MAP[read_result.outcome]
            result_payload = (
                {"raw": read_result.extraction.raw, "fields": read_result.extraction.fields}
                if read_result.extraction is not None
                else None
            )
            await self._persist_stage(
                service,
                existing,
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.OCR_EXTRACTION,
                status=status,
                reason_codes=(reason_code,) if reason_code else (),
                result=result_payload,
                producer=_PRODUCER_OCR,
                source_reference=capture_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            await session.commit()
