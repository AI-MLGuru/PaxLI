"""BD-001 Slice G (BD-001.2 §5): the first real implementation of
`core.face.reference.ReferenceSourceResolver` -- route (A) only, per
BP-001 §6b. Mirrors `infrastructure.document.processor`'s own
dependency-inversion shape (`core/` depends only on the narrow ABC,
never on SQLAlchemy) and its per-call session lifecycle, but is
otherwise a much smaller thing: this resolver persists nothing of its
own (BD-001.1 G-6) -- it opens one read-only session, decides an
outcome, and returns.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.audit.service import AuditService
from core.evidence.enums import EvidenceType
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.service import EvidenceResultService
from core.face.capabilities import DocumentFaceExtractor
from core.face.reference import (
    ReferenceAcquisitionOutcome,
    ReferenceArtifactImage,
    ReferenceIdentity,
    ReferenceProvenance,
    ReferenceResolution,
    ReferenceSourceResolver,
)
from core.face.types import DocumentFaceExtractionOutcome
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import SqlAlchemyEvidenceResultRepository

if TYPE_CHECKING:
    from core.security.keys import KeyProvider
    from infrastructure.storage.interface import ObjectStorage

# BD-001.2 D-2b: DocumentFaceExtractionOutcome's non-VALID members map
# onto ReferenceAcquisitionOutcome without adding a fifth member there
# -- VALID is handled separately below since it also builds a
# ReferenceIdentity, not just an outcome.
_EXTRACTION_OUTCOME_MAP: dict[DocumentFaceExtractionOutcome, ReferenceAcquisitionOutcome] = {
    DocumentFaceExtractionOutcome.UNREADABLE: ReferenceAcquisitionOutcome.NOT_AVAILABLE,
    DocumentFaceExtractionOutcome.NO_FACE: ReferenceAcquisitionOutcome.NO_FACE_FOUND,
    DocumentFaceExtractionOutcome.AMBIGUOUS: ReferenceAcquisitionOutcome.AMBIGUOUS,
}


class DocumentBoundReferenceResolver(ReferenceSourceResolver):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        key_provider: "KeyProvider",
        key_id: str,
        storage: "ObjectStorage",
        document_face_extractor: DocumentFaceExtractor,
    ) -> None:
        self._session_factory = session_factory
        self._key_provider = key_provider
        self._key_id = key_id
        self._storage = storage
        self._document_face_extractor = document_face_extractor

    async def resolve(self, *, session_id: UUID, tenant_id: str) -> ReferenceResolution:
        async with self._session_factory() as session:
            evidence_repository = SqlAlchemyEvidenceRepository(session)
            captures = [
                evidence
                for evidence in await evidence_repository.list_for_session(session_id, tenant_id)
                if evidence.evidence_type is EvidenceType.DOCUMENT
            ]
            if len(captures) != 1:
                # Independently derived -- never borrowed from
                # DocumentProcessor's own internal ambiguous-capture
                # flag (DP-001 Decision 3's "independently addressable
                # capability operations" principle, applied one layer
                # up). Zero or 2+ DOCUMENT captures both mean
                # NOT_AVAILABLE (BD-001.2 §5 step 2).
                return ReferenceResolution(
                    outcome=ReferenceAcquisitionOutcome.NOT_AVAILABLE, identity=None
                )
            capture = captures[0]

            service = EvidenceResultService(
                SqlAlchemyEvidenceResultRepository(session, self._key_provider, self._key_id),
                AuditService(SqlAlchemyAuditEventRepository(session)),
                evidence_repository,
            )
            field_extraction_row = await service.get_effective_for_session_by_type(
                session_id=session_id,
                tenant_id=tenant_id,
                evidence_type=EvidenceResultType.DOCUMENT_FIELD_EXTRACTION,
            )
            if (
                field_extraction_row is None
                or field_extraction_row.status is EvidenceResultStatus.UNAVAILABLE
            ):
                # No effective row yet, or the retryable case -- either
                # way, upstream document processing hasn't produced a
                # usable result yet (BD-001.2 §5 step 3). A row here
                # with status=INCONCLUSIVE cannot be the ambiguous-
                # capture case: step 2 above already independently
                # ruled out 0/2+ DOCUMENT captures, so any INCONCLUSIVE
                # row seen here is the unrelated field-conflict case
                # (BD-001.2 §5's own note) -- eligible to proceed.
                return ReferenceResolution(
                    outcome=ReferenceAcquisitionOutcome.NOT_AVAILABLE, identity=None
                )

            image = await self._storage.get(capture.object_key)

        # extract_candidate() runs outside the session -- it performs no
        # database I/O of its own, and there is no reason to hold a
        # connection open across an InsightFace call.
        # CapabilityUnavailableError propagates uncaught (BD-001.2 D-3):
        # this resolver persists nothing and has no legitimate place to
        # catch and reinterpret a genuine provider/runtime failure.
        result = await self._document_face_extractor.extract_candidate(image)

        if result.outcome is DocumentFaceExtractionOutcome.VALID:
            # VALID implies image is populated, per
            # DocumentFaceExtractionResult's own frozen "populated iff
            # VALID" contract, confirmed structurally by
            # DocumentFaceExtractor, not re-validated here.
            assert result.image is not None
            return ReferenceResolution(
                outcome=ReferenceAcquisitionOutcome.RESOLVED,
                identity=ReferenceIdentity(
                    identity_claim=field_extraction_row.id,
                    reference_artifact=ReferenceArtifactImage(kind="IMAGE", image=result.image),
                    provenance=ReferenceProvenance(
                        acquisition_route="DOCUMENT_BOUND",
                        source_evidence_result_ids=(field_extraction_row.id,),
                    ),
                ),
            )

        return ReferenceResolution(outcome=_EXTRACTION_OUTCOME_MAP[result.outcome], identity=None)
