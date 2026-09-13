"""DP-002 Phase 1 / DP-003-DP-004 Phase 2: deterministic capability
implementations.

Phase 1's QualityAssessor/DocumentClassifier prove the DocumentProcessor
orchestration/lineage/persistence path -- they are NOT a stand-in for
real quality/classification models and must not be mistaken for one.
Both have an easily-triggered path to their *unsatisfying* outcome as
well as their happy path, deliberately.

Phase 2's MRZParser/BarcodeDecoder are NOT both fully fake the same way
(DP-003 Decision 8): zone-detection/text-extraction is a stand-in here
(marker-driven, like DocumentClassifier's marker lookup), but check-
digit validation (core.document.mrz) is real ICAO 9303 logic -- a fake
check-digit validator would misrepresent what this phase actually
proves. BarcodeDecoder has no equivalent real subset and is a full
stand-in, mirroring DocumentClassifier's pattern exactly.

All marker-extraction helpers below are private implementation
scaffolding, NOT part of any capability's externally observable
contract (DP-004's marker-mechanism safety boundary) -- they match only
their own exact literal prefix, never interpret arbitrary document
content as an instruction, and fail safe (None/UNREADABLE) rather than
raising on anything that isn't their own recognized format, since they
run against real, attacker-controlled document bytes in production
exactly like DeterministicQualityAssessor/DeterministicDocumentClassifier
already do.
"""

from dataclasses import dataclass

from core.document.capabilities import (
    BarcodeDecoder,
    DocumentClassifier,
    MRZParser,
    QualityAssessor,
)
from core.document.mrz import parse_icao9303_structure, validate_check_digits
from core.document.types import (
    BarcodeExtraction,
    BarcodeReadOutcome,
    BarcodeReadResult,
    DocumentClassification,
    MRZExtraction,
    MRZReadOutcome,
    MRZReadResult,
    QualityAssessment,
)
from core.evidence_result.enums import DocumentType

# A pure, content-independent stand-in signal -- never a real blur/glare/
# crop model. Content below this size cannot plausibly be a real document
# photo; this exists to exercise DocumentProcessor's PASS/FAIL mapping,
# not to assess real image quality.
_MINIMUM_PLAUSIBLE_SIZE_BYTES = 1024

# Fixed, inspectable byte markers -- not ML, not a real classifier. A
# real DocumentClassifier (Phase 3+) replaces this entirely; this one
# exists to prove the pipeline, including its DOCUMENT_UNSUPPORTED path.
_CLASSIFICATION_MARKERS: dict[bytes, DocumentType] = {
    b"PAXLI_TEST_STANDARD_NIN_SLIP": DocumentType.STANDARD_NIN_SLIP,
    b"PAXLI_TEST_IMPROVED_NIN_SLIP": DocumentType.IMPROVED_NIN_SLIP,
    b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE": DocumentType.ICAO_PASSPORT_DATA_PAGE,
}


class DeterministicQualityAssessor(QualityAssessor):
    async def assess(self, image: bytes) -> QualityAssessment:
        score = 1.0 if len(image) >= _MINIMUM_PLAUSIBLE_SIZE_BYTES else 0.0
        return QualityAssessment(quality_score=score)


class DeterministicDocumentClassifier(DocumentClassifier):
    async def classify(self, image: bytes) -> DocumentClassification:
        for marker, document_type in _CLASSIFICATION_MARKERS.items():
            if marker in image:
                return DocumentClassification(document_type=document_type, confidence=1.0)
        return DocumentClassification(document_type=None, confidence=None)


# --- MRZ ---------------------------------------------------------------

_MRZ_MARKER_PREFIX = b"PAXLI_TEST_MRZ:"
_MRZ_UNREADABLE_MARKER = b"PAXLI_TEST_MRZ_UNREADABLE"
_MRZ_RAW_LENGTH = 88  # two 44-character TD3 lines, concatenated


def _extract_mrz_test_marker(image: bytes) -> str | None:
    """Returns None (no marker at all -> MRZ=NOT_SUBMITTED), "" (the
    explicit unreadable marker, or a found marker whose payload can't
    even be decoded as text -> MRZReadOutcome.UNREADABLE), or the raw
    88-character MRZ text following a found-MRZ marker. Matches only the
    exact literal prefixes above -- never a fuzzy/partial match, never
    an interpretation of arbitrary document content."""
    if _MRZ_UNREADABLE_MARKER in image:
        return ""
    index = image.find(_MRZ_MARKER_PREFIX)
    if index == -1:
        return None
    start = index + len(_MRZ_MARKER_PREFIX)
    raw_bytes = image[start : start + _MRZ_RAW_LENGTH]
    try:
        return raw_bytes.decode("ascii")
    except UnicodeDecodeError:
        return ""


class DeterministicMRZParser(MRZParser):
    """Zone-detection/text-extraction is a stand-in (fixed test-marker
    driven) -- structural TD3 parsing and ICAO 9303 check-digit
    validation (core.document.mrz) are REAL, not faked (DP-003
    Decision 8)."""

    async def parse(self, image: bytes) -> MRZReadResult | None:
        marker_text = _extract_mrz_test_marker(image)
        if marker_text is None:
            return None
        if not marker_text:
            return MRZReadResult(outcome=MRZReadOutcome.UNREADABLE, extraction=None)
        parsed = parse_icao9303_structure(marker_text)
        if parsed is None:
            return MRZReadResult(
                outcome=MRZReadOutcome.MALFORMED,
                extraction=MRZExtraction(raw=marker_text, fields={}),
            )
        valid = validate_check_digits(parsed)
        return MRZReadResult(
            outcome=MRZReadOutcome.VALID if valid else MRZReadOutcome.CHECK_DIGIT_MISMATCH,
            extraction=MRZExtraction(raw=marker_text, fields=parsed.fields),
        )


# --- Barcode/QR ----------------------------------------------------------

_BARCODE_UNREADABLE_MARKER = b"PAXLI_TEST_BARCODE_UNREADABLE"
_BARCODE_VALID_PREFIX = b"PAXLI_TEST_BARCODE_VALID:"
_BARCODE_MALFORMED_PREFIX = b"PAXLI_TEST_BARCODE_MALFORMED:"
_BARCODE_UNRECOGNIZED_PREFIX = b"PAXLI_TEST_BARCODE_UNRECOGNIZED:"
_BARCODE_MARKER_TERMINATOR = b"\x00"
_BARCODE_PAYLOAD_MAX_BYTES = 512


@dataclass(frozen=True)
class _BarcodeTestMarker:
    outcome: BarcodeReadOutcome
    symbology: str | None
    raw: str
    fields: dict[str, str]


def _parse_kv_payload(text: str) -> dict[str, str]:
    """`key=value;key=value` -- an arbitrary, deterministic test schema,
    not any real barcode payload standard (there is no real decoder
    behind this capability, DP-003 Decision 8)."""
    fields: dict[str, str] = {}
    for pair in text.split(";"):
        key, sep, value = pair.partition("=")
        if sep and key:
            fields[key] = value
    return fields


def _extract_barcode_test_marker(image: bytes) -> _BarcodeTestMarker | None:
    """Returns None (no marker at all -> BARCODE_QR=NOT_SUBMITTED) or an
    explicit outcome marker. Matches only the exact literal prefixes
    above -- never a fuzzy/partial match, never an interpretation of
    arbitrary document content. A found marker whose payload can't be
    decoded as text degrades to UNREADABLE, never an exception."""
    if _BARCODE_UNREADABLE_MARKER in image:
        return _BarcodeTestMarker(
            outcome=BarcodeReadOutcome.UNREADABLE, symbology=None, raw="", fields={}
        )
    for prefix, outcome in (
        (_BARCODE_VALID_PREFIX, BarcodeReadOutcome.VALID),
        (_BARCODE_MALFORMED_PREFIX, BarcodeReadOutcome.PAYLOAD_MALFORMED),
        (_BARCODE_UNRECOGNIZED_PREFIX, BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED),
    ):
        index = image.find(prefix)
        if index == -1:
            continue
        start = index + len(prefix)
        max_end = start + _BARCODE_PAYLOAD_MAX_BYTES
        end = image.find(_BARCODE_MARKER_TERMINATOR, start, max_end)
        raw_bytes = image[start:end] if end != -1 else image[start:max_end]
        try:
            text = raw_bytes.decode("ascii")
        except UnicodeDecodeError:
            return _BarcodeTestMarker(
                outcome=BarcodeReadOutcome.UNREADABLE, symbology=None, raw="", fields={}
            )
        symbology, _, payload = text.partition(":")
        is_unrecognized = outcome is BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED
        fields = {} if is_unrecognized else _parse_kv_payload(payload)
        return _BarcodeTestMarker(
            outcome=outcome, symbology=symbology or None, raw=payload, fields=fields
        )
    return None


class DeterministicBarcodeDecoder(BarcodeDecoder):
    """Fully stand-in -- no real symbology-decode logic (DP-003
    Decision 8), mirroring DeterministicDocumentClassifier's pattern
    exactly. Real decoding is deferred to a future real-adapter phase."""

    async def decode(self, image: bytes) -> BarcodeReadResult | None:
        marker = _extract_barcode_test_marker(image)
        if marker is None:
            return None
        if marker.outcome is BarcodeReadOutcome.UNREADABLE:
            return BarcodeReadResult(outcome=BarcodeReadOutcome.UNREADABLE, extraction=None)
        return BarcodeReadResult(
            outcome=marker.outcome,
            extraction=BarcodeExtraction(
                raw=marker.raw, symbology=marker.symbology, fields=marker.fields
            ),
        )
