"""BD-001 Slice G / BP-001.5 Decision 18: the reference-acquisition
boundary that lets `BiometricProcessor` (BD-001 Slice G.2, not yet
built) consume a resolved reference identity without ever knowing
whether it came from a document scan, a NIN Data Print, or an external
provider (BP-001 §6d's frozen principle). `ReferenceSourceResolver` is
the abstract dependency `BiometricProcessor` will hold;
`DocumentBoundReferenceResolver` (infrastructure/face/) is this demo's
one concrete implementation -- route (A) only, per BP-001 §6b.

Deliberately a separate module from `core.face.capabilities`: these
types do not share that module's `image: bytes -> domain result`
contract shape (`resolve()` takes `session_id`/`tenant_id`, not image
bytes) -- the same "different call shape, different module" reasoning
that already separates `core.face.matcher` from `core.face.capabilities`.

`ReferenceIdentity`/`ReferenceArtifact`/`ReferenceProvenance` are
transient domain values assembled by the resolver -- never a persisted
`EvidenceResultType`, never a new evidence-result row (BP Decision 18).
`ReferenceArtifact` is a tagged union scoped to *shape* (image vs.
already-computed embedding), never to *source* -- BP-001.5 §1's own
reasoning: without it, whatever consumes a `ReferenceIdentity` would
have no principled way to know which stages apply to the reference
side, and would end up special-casing acquisition routes exactly where
BP Decision 13 forbids it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID

from core.face.types import FaceEmbedding

__all__ = [
    "ReferenceAcquisitionOutcome",
    "ReferenceArtifact",
    "ReferenceArtifactEmbedding",
    "ReferenceArtifactImage",
    "ReferenceIdentity",
    "ReferenceProvenance",
    "ReferenceResolution",
    "ReferenceSourceResolver",
]


class ReferenceAcquisitionOutcome(StrEnum):
    """BD-001 Slice G's own frozen outcome vocabulary (unchanged by
    BD-001.1/BD-001.2 -- see BD-001.2 D-2b for how
    `DocumentFaceExtractionOutcome` maps onto this without adding a
    fifth member here).

    `NOT_AVAILABLE`/`NO_FACE_FOUND`/`AMBIGUOUS` all mean "no
    reference-side rows produced this attempt" -- not an error; the
    same "no row until ready" principle BP-001.5 §5 established for the
    match attempt itself, applied one layer earlier, to reference
    *acquisition*."""

    NOT_AVAILABLE = "NOT_AVAILABLE"  # no DOCUMENT capture, ambiguous
    # DOCUMENT capture, upstream document processing not yet effective,
    # or the document image itself could not be decoded for extraction
    NO_FACE_FOUND = "NO_FACE_FOUND"  # document image had zero detectable faces
    AMBIGUOUS = "AMBIGUOUS"  # document image had 2+ detectable faces -- no selection, ever
    RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class ReferenceProvenance:
    """BP Decision 18. `acquisition_route` names which of BP-001 §6b's
    routes produced this reference -- never "SESSION_INTERNAL" (route
    (C)), which BP Decision 6 already rejects as unconstructable here.
    `source_evidence_result_ids` names what established the identity
    claim (e.g. a DOCUMENT_FIELD_EXTRACTION row's id) -- read by
    generic, evidence-type-agnostic lineage machinery, never by a
    consumer needing to know a *role* (that is `identity_claim`'s job,
    on `ReferenceIdentity` below)."""

    acquisition_route: Literal[
        "DOCUMENT_BOUND", "NIN_DATA_PRINT_BOUND", "EXTERNAL_PROVIDER_BOUND"
    ]
    source_evidence_result_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ReferenceArtifactImage:
    """The (A)/(A') shape when a provider/document returns a
    photograph: a face region still needing FaceDetector /
    FaceQualityAssessor / FaceEmbedder (BP-001.5 §1). `image` is the
    already-cropped face region's bytes (BD-001.1 G-3) -- this demo's
    `DocumentBoundReferenceResolver` never constructs this variant with
    anything but a `DocumentFaceExtractor`-produced crop."""

    kind: Literal["IMAGE"]
    image: bytes


@dataclass(frozen=True)
class ReferenceArtifactEmbedding:
    """The (B) shape (i) when a provider returns a biometric
    template/embedding directly (BP-001 §6c). Never constructed by this
    slice -- route (B) and (A')'s embedding sub-case both stay OPEN per
    BP-001 §6c/§7. Exists now so BP Decision 18's tagged union is
    complete, and a future `BiometricProcessor` (Slice G.2) can already
    branch on `kind` without a later redesign."""

    kind: Literal["EMBEDDING"]
    embedding: FaceEmbedding


ReferenceArtifact = ReferenceArtifactImage | ReferenceArtifactEmbedding


@dataclass(frozen=True)
class ReferenceIdentity:
    """BP Decision 18's full specification. `identity_claim` points at
    whatever established WHO this reference asserts to be -- not
    duplicated data, a reference (for this slice, the same
    `DOCUMENT_FIELD_EXTRACTION` row id that also appears in
    `provenance.source_evidence_result_ids`; intentional duplication,
    not an oversight, mirroring `FaceMatchResult`'s own
    reference/probe-id-vs-parent-set precedent, BP Decision 20 -- the
    two fields serve two structurally different future readers: an
    identity-claim consumer vs. generic, evidence-type-agnostic
    lineage machinery)."""

    identity_claim: UUID
    reference_artifact: ReferenceArtifact
    provenance: ReferenceProvenance


@dataclass(frozen=True)
class ReferenceResolution:
    """Always populated, never a bare Optional -- mirrors
    `OCRReadResult`/`MRZReadResult`'s own outcome+payload pattern
    (`core.document.types`) rather than collapsing distinguishable
    outcomes into None."""

    outcome: ReferenceAcquisitionOutcome
    identity: ReferenceIdentity | None  # populated iff outcome=RESOLVED


class ReferenceSourceResolver(ABC):
    """The abstract dependency `BiometricProcessor` (Slice G.2) will
    hold -- wired, at the composition root only, to whichever concrete
    resolver a given deployment needs. `BiometricProcessor` calls
    `resolve()` once per attempt, has no knowledge of which concrete
    class is behind this interface, and would require zero change the
    day a second resolver (e.g. NIN Data Print-bound) exists."""

    @abstractmethod
    async def resolve(self, *, session_id: UUID, tenant_id: str) -> ReferenceResolution:
        """Always returns a populated ReferenceResolution -- never
        None. May raise `CapabilityUnavailableError`
        (`core.face.capabilities`), propagated uncaught from whatever
        capability this resolver calls internally -- a genuine
        provider/runtime failure, never `NOT_AVAILABLE`, which means
        something structurally different ("nothing to acquire from yet
        or at all"). This resolver persists nothing of its own; a
        caught `CapabilityUnavailableError` would have nowhere
        legitimate to go except a misleading reinterpretation as
        `NOT_AVAILABLE` -- BD-001.2 D-3."""
        raise NotImplementedError
