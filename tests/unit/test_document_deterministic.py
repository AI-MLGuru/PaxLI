"""DP-002 Phase 1: DeterministicQualityAssessor/DeterministicDocumentClassifier
are pure, content-independent stand-ins that prove DocumentProcessor's
orchestration/lineage/persistence path -- never real quality/classification
models. Both the PASS/happy path and the FAIL/unsupported path are
exercised deliberately, not just the happy one (DP-002 §2).

DP-003/DP-004 Phase 2: DeterministicMRZParser's zone-detection is an
equivalent stand-in, but its check-digit validation is REAL (see
tests/unit/test_mrz.py for that logic's own dedicated coverage) --
tests here only confirm the outcome-wrapper plumbing around it.
DeterministicBarcodeDecoder is a full stand-in, mirroring
DeterministicDocumentClassifier's pattern exactly.

DP-005/DP-006 Phase 3: DeterministicOCREngine is a full stand-in too
(no equivalent to MRZ's real check-digit subset exists for OCR)."""

import pytest

from core.document.deterministic import (
    DeterministicBarcodeDecoder,
    DeterministicDocumentClassifier,
    DeterministicMRZParser,
    DeterministicOCREngine,
    DeterministicQualityAssessor,
)
from core.document.types import BarcodeReadOutcome, MRZReadOutcome, OCRReadOutcome
from core.evidence_result.enums import DocumentType
from tests.unit.test_mrz import _LINE1, _LINE2, _VALID_RAW

MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


@pytest.mark.asyncio
async def test_quality_assessor_passes_plausibly_sized_content() -> None:
    assessor = DeterministicQualityAssessor()
    assessment = await assessor.assess(MINIMAL_JPEG_BYTES + b"0" * 2000)
    assert assessment.quality_score == 1.0


@pytest.mark.asyncio
async def test_quality_assessor_fails_implausibly_small_content() -> None:
    assessor = DeterministicQualityAssessor()
    assessment = await assessor.assess(MINIMAL_JPEG_BYTES)
    assert assessment.quality_score == 0.0


@pytest.mark.asyncio
async def test_classifier_recognizes_each_catalog_member() -> None:
    classifier = DeterministicDocumentClassifier()
    for marker, expected in (
        (b"PAXLI_TEST_STANDARD_NIN_SLIP", DocumentType.STANDARD_NIN_SLIP),
        (b"PAXLI_TEST_IMPROVED_NIN_SLIP", DocumentType.IMPROVED_NIN_SLIP),
        (b"PAXLI_TEST_ICAO_PASSPORT_DATA_PAGE", DocumentType.ICAO_PASSPORT_DATA_PAGE),
    ):
        classification = await classifier.classify(MINIMAL_JPEG_BYTES + marker)
        assert classification.document_type is expected
        assert classification.confidence == 1.0


@pytest.mark.asyncio
async def test_classifier_reports_unrecognized_document_as_none() -> None:
    """The DOCUMENT_UNSUPPORTED path (DP-001 Decision 5) must be
    deliberately reachable, not just the happy path."""
    classifier = DeterministicDocumentClassifier()
    classification = await classifier.classify(MINIMAL_JPEG_BYTES + b"not a known document")
    assert classification.document_type is None
    assert classification.confidence is None


# --- DeterministicMRZParser (DP-003/DP-004 Phase 2) ---------------------


@pytest.mark.asyncio
async def test_mrz_parser_returns_none_with_no_marker() -> None:
    parser = DeterministicMRZParser()
    assert await parser.parse(MINIMAL_JPEG_BYTES + b"an ordinary document, no MRZ") is None


@pytest.mark.asyncio
async def test_mrz_parser_reports_unreadable() -> None:
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_MRZ_UNREADABLE")
    assert result is not None
    assert result.outcome is MRZReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_mrz_parser_reports_malformed() -> None:
    parser = DeterministicMRZParser()
    marker = b"PAXLI_TEST_MRZ:" + b"not a valid td3 mrz at all" + b"0" * 20
    result = await parser.parse(MINIMAL_JPEG_BYTES + marker)
    assert result is not None
    assert result.outcome is MRZReadOutcome.MALFORMED
    assert result.extraction is not None
    assert result.extraction.fields == {}


@pytest.mark.asyncio
async def test_mrz_parser_reports_check_digit_mismatch() -> None:
    corrupted_line2 = _LINE2[:9] + "5" + _LINE2[10:]  # document-number check digit was 6
    marker = b"PAXLI_TEST_MRZ:" + (_LINE1 + corrupted_line2).encode("ascii")
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + marker)
    assert result is not None
    assert result.outcome is MRZReadOutcome.CHECK_DIGIT_MISMATCH
    assert result.extraction is not None
    assert result.extraction.fields["document_number"] == "L898902C3"


@pytest.mark.asyncio
async def test_mrz_parser_reports_valid() -> None:
    marker = b"PAXLI_TEST_MRZ:" + _VALID_RAW.encode("ascii")
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + marker)
    assert result is not None
    assert result.outcome is MRZReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == _VALID_RAW
    assert result.extraction.fields["surname"] == "ERIKSSON"


@pytest.mark.asyncio
async def test_mrz_parser_never_interprets_incidental_substrings() -> None:
    """The marker-safety boundary (DP-004): real document content that
    happens to contain 'PAXLI_TEST_MRZ' without the exact ':' prefix
    must never be misinterpreted as an instruction."""
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + b"discussing PAXLI_TEST_MRZ_PARSER in a memo")
    assert result is None


# --- DeterministicBarcodeDecoder (DP-003/DP-004 Phase 2) ----------------


@pytest.mark.asyncio
async def test_barcode_decoder_returns_none_with_no_marker() -> None:
    decoder = DeterministicBarcodeDecoder()
    assert await decoder.decode(MINIMAL_JPEG_BYTES + b"an ordinary document, no barcode") is None


@pytest.mark.asyncio
async def test_barcode_decoder_reports_unreadable() -> None:
    decoder = DeterministicBarcodeDecoder()
    result = await decoder.decode(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_BARCODE_UNREADABLE")
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_barcode_decoder_reports_payload_unrecognized() -> None:
    decoder = DeterministicBarcodeDecoder()
    marker = b"PAXLI_TEST_BARCODE_UNRECOGNIZED:QR_CODE:opaque-reference-token\x00"
    result = await decoder.decode(MINIMAL_JPEG_BYTES + marker)
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED
    assert result.extraction is not None
    assert result.extraction.symbology == "QR_CODE"
    assert result.extraction.fields == {}


@pytest.mark.asyncio
async def test_barcode_decoder_reports_payload_malformed() -> None:
    decoder = DeterministicBarcodeDecoder()
    marker = b"PAXLI_TEST_BARCODE_MALFORMED:PDF417:document_number=\x00"
    result = await decoder.decode(MINIMAL_JPEG_BYTES + marker)
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.PAYLOAD_MALFORMED
    assert result.extraction is not None
    assert result.extraction.symbology == "PDF417"


@pytest.mark.asyncio
async def test_barcode_decoder_reports_valid() -> None:
    decoder = DeterministicBarcodeDecoder()
    marker = b"PAXLI_TEST_BARCODE_VALID:PDF417:document_number=A1234567;surname=DOE\x00"
    result = await decoder.decode(MINIMAL_JPEG_BYTES + marker)
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.symbology == "PDF417"
    assert result.extraction.fields == {"document_number": "A1234567", "surname": "DOE"}


@pytest.mark.asyncio
async def test_barcode_decoder_never_interprets_incidental_substrings() -> None:
    decoder = DeterministicBarcodeDecoder()
    result = await decoder.decode(
        MINIMAL_JPEG_BYTES + b"discussing PAXLI_TEST_BARCODE_READER in a memo"
    )
    assert result is None


# --- HV-011: marker-boundary and adversarial-input hostile tests --------


@pytest.mark.asyncio
async def test_mrz_marker_at_end_of_image_with_no_payload_is_unreadable_not_a_crash() -> None:
    """The prefix present with zero bytes following it (image truncated
    exactly at the marker) must degrade safely, never raise."""
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_MRZ:")
    assert result is not None
    assert result.outcome is MRZReadOutcome.UNREADABLE


@pytest.mark.asyncio
async def test_mrz_marker_followed_by_non_ascii_bytes_degrades_to_unreadable() -> None:
    """A marker prefix genuinely found, but whose payload can't even be
    decoded as text, must not raise UnicodeDecodeError out of the
    capability -- confirmed against real invalid-UTF-8 bytes, not just
    the explicit UNREADABLE marker."""
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_MRZ:" + b"\xff\xfe\x00\x01" * 20)
    assert result is not None
    assert result.outcome is MRZReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_mrz_marker_found_amid_large_surrounding_binary_noise() -> None:
    """The marker prefix must be located correctly regardless of how much
    unrelated noise surrounds it on either side -- a real document photo
    is exactly this shape (thousands of bytes of image data around any
    incidental byte sequence)."""
    noise_before = bytes((i * 37) % 256 for i in range(5000))
    noise_after = bytes((i * 53) % 256 for i in range(5000))
    marker = b"PAXLI_TEST_MRZ:" + _VALID_RAW.encode("ascii")
    parser = DeterministicMRZParser()
    result = await parser.parse(noise_before + marker + noise_after)
    assert result is not None
    assert result.outcome is MRZReadOutcome.VALID


@pytest.mark.asyncio
async def test_mrz_unreadable_marker_takes_precedence_when_both_markers_present() -> None:
    """Two conflicting markers present simultaneously is itself an
    adversarial/malformed-fixture shape -- the important property is that
    behavior is deterministic and safe, not undefined. Confirmed
    explicitly rather than left as an accident of dict/string ordering."""
    both = b"PAXLI_TEST_MRZ_UNREADABLE" + b"PAXLI_TEST_MRZ:" + _VALID_RAW.encode("ascii")
    parser = DeterministicMRZParser()
    result = await parser.parse(MINIMAL_JPEG_BYTES + both)
    assert result is not None
    assert result.outcome is MRZReadOutcome.UNREADABLE


@pytest.mark.asyncio
async def test_barcode_marker_precedence_is_deterministic_when_multiple_present() -> None:
    """Same property for barcode's three prefix markers -- VALID is
    checked first in the implementation; confirmed directly so this
    ordering is a tested contract, not an implementation accident a
    future refactor could silently invert."""
    both = (
        b"PAXLI_TEST_BARCODE_VALID:PDF417:document_number=A1\x00"
        + b"PAXLI_TEST_BARCODE_MALFORMED:QR_CODE:bad\x00"
    )
    decoder = DeterministicBarcodeDecoder()
    result = await decoder.decode(MINIMAL_JPEG_BYTES + both)
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.VALID


@pytest.mark.asyncio
async def test_barcode_payload_without_terminator_is_truncated_not_unbounded() -> None:
    """No null-byte terminator anywhere in the rest of the image must not
    scan unboundedly or crash -- truncates at _BARCODE_PAYLOAD_MAX_BYTES."""
    huge_untruncated_payload = b"A" * 10_000
    decoder = DeterministicBarcodeDecoder()
    result = await decoder.decode(
        MINIMAL_JPEG_BYTES + b"PAXLI_TEST_BARCODE_VALID:PDF417:" + huge_untruncated_payload
    )
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.VALID
    assert result.extraction is not None
    assert len(result.extraction.raw) < 10_000  # truncated, not the full 10k payload


@pytest.mark.asyncio
async def test_barcode_marker_followed_by_non_ascii_bytes_degrades_to_unreadable() -> None:
    decoder = DeterministicBarcodeDecoder()
    result = await decoder.decode(
        MINIMAL_JPEG_BYTES + b"PAXLI_TEST_BARCODE_VALID:" + b"\xff\xfe\x00\x01" * 20
    )
    assert result is not None
    assert result.outcome is BarcodeReadOutcome.UNREADABLE
    assert result.extraction is None


# --- DeterministicOCREngine (DP-005/DP-006 Phase 3) ---------------------


@pytest.mark.asyncio
async def test_ocr_engine_reports_unreadable_with_no_marker() -> None:
    """DP-005 Decision 3: OCR has no NOT_SUBMITTED outcome -- a missing
    marker (the "nothing to recognize" case) still degrades to
    UNREADABLE, never None, unlike MRZ/Barcode's parse()/decode()."""
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + b"an ordinary document, no OCR marker")
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_reports_unreadable_with_explicit_marker() -> None:
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_UNREADABLE")
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_reports_valid() -> None:
    engine = DeterministicOCREngine()
    marker = b"PAXLI_TEST_OCR_VALID:FEDERAL REPUBLIC OF NIGERIA;surname=DOE\x00"
    result = await engine.extract(MINIMAL_JPEG_BYTES + marker)
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == "FEDERAL REPUBLIC OF NIGERIA;surname=DOE"
    assert result.extraction.fields == {"surname": "DOE"}


@pytest.mark.asyncio
async def test_ocr_engine_fields_ignore_segments_without_equals() -> None:
    """_parse_ocr_fields()'s deterministic contract (DP-006 §4): a
    segment with no '=' is silently ignored, not an error."""
    engine = DeterministicOCREngine()
    marker = b"PAXLI_TEST_OCR_VALID:not a field;surname=DOE;also not a field\x00"
    result = await engine.extract(MINIMAL_JPEG_BYTES + marker)
    assert result.extraction is not None
    assert result.extraction.fields == {"surname": "DOE"}


@pytest.mark.asyncio
async def test_ocr_engine_never_interprets_incidental_substrings() -> None:
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES + b"discussing PAXLI_TEST_OCR_ENGINE in a memo"
    )
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_marker_at_end_of_image_with_no_payload_is_unreadable() -> None:
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_VALID:")
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_marker_found_amid_large_surrounding_binary_noise() -> None:
    noise_before = bytes((i * 37) % 256 for i in range(5000))
    noise_after = bytes((i * 53) % 256 for i in range(5000))
    marker = b"PAXLI_TEST_OCR_VALID:recognized text\x00"
    engine = DeterministicOCREngine()
    result = await engine.extract(noise_before + marker + noise_after)
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == "recognized text"


@pytest.mark.asyncio
async def test_ocr_engine_unreadable_marker_takes_precedence_when_both_present() -> None:
    """Marker precedence (DP-006 §4): if both markers are present, the
    explicit unreadable marker wins -- checked first, unconditionally."""
    both = b"PAXLI_TEST_OCR_UNREADABLE" + b"PAXLI_TEST_OCR_VALID:some text\x00"
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + both)
    assert result.outcome is OCRReadOutcome.UNREADABLE


@pytest.mark.asyncio
async def test_ocr_engine_payload_without_terminator_is_truncated() -> None:
    huge_untruncated_payload = b"A" * 10_000
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_VALID:" + huge_untruncated_payload
    )
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert len(result.extraction.raw) < 10_000


@pytest.mark.asyncio
async def test_ocr_engine_carries_adversarial_unicode_through_the_full_pipeline() -> None:
    """DP-006 §4's deliberate utf-8 (not ascii) decoding choice: OCR is
    the one capability whose real output is genuinely unconstrained
    Unicode (SEC-7.21) -- confirmed here that the deterministic stand-in
    actually carries right-to-left script, combining characters, and a
    zero-width character through cleanly, giving HV-012 a real surface
    to attack rather than an artificially ASCII-only one."""
    adversarial_text = "مرحباً é​ test"  # Arabic + combining + ZWSP
    marker = f"PAXLI_TEST_OCR_VALID:{adversarial_text}\x00".encode()
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + marker)
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == adversarial_text


@pytest.mark.asyncio
async def test_ocr_engine_non_utf8_bytes_degrade_to_unreadable_not_a_crash() -> None:
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_VALID:" + b"\xff\xfe\x00\x01" * 20
    )
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


# --- HV-012: hostile validation of the OCR surface ----------------------
#
# Scoped tightly to the new OCR capability -- attacking the marker
# mechanism's byte-boundary math, Unicode handling, and matching
# exactness directly, per the frozen HV-012 attack matrix. Findings are
# recorded as they are found, not silently patched.


@pytest.mark.asyncio
async def test_ocr_engine_payload_truncated_mid_multibyte_character_degrades_to_unreadable_not_a_crash() -> None:  # noqa: E501
    """The truncation window (_OCR_PAYLOAD_MAX_BYTES) is a raw byte slice,
    not Unicode-aware -- an untruncated payload built entirely from
    multi-byte characters can have its max-length slice land mid-
    character, producing an invalid UTF-8 tail. Confirmed here that this
    degrades to UNREADABLE via the existing UnicodeDecodeError catch,
    never an uncaught exception out of extract()."""
    # U+8BED ("语") is 3 bytes in UTF-8; 700 repetitions = 2100 bytes, so
    # the 2048-byte truncation boundary falls inside the 683rd character
    # (2046 = 682 * 3), never on a character boundary.
    payload = "语" * 700
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_VALID:" + payload.encode("utf-8")
    )
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_control_characters_survive_in_raw_payload() -> None:
    """Only the NUL terminator is structurally significant to the marker
    mechanism -- other C0 control characters (SOH, ESC, BEL) are ordinary
    payload bytes and must pass through raw unmodified, not be stripped
    or treated as additional terminators."""
    payload = "line1\x01\x1b\x07line2"
    marker = f"PAXLI_TEST_OCR_VALID:{payload}\x00".encode()
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + marker)
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == payload


@pytest.mark.asyncio
async def test_ocr_engine_homoglyph_prefix_does_not_match_valid_marker() -> None:
    """Marker matching is exact-literal-byte, never fuzzy -- a Cyrillic
    'А' (U+0410) substituted for the first Latin 'A' in the VALID
    prefix must NOT be recognized as the marker, ruling out a homoglyph
    spoof either falsely triggering or falsely masking OCR's outcome."""
    homoglyph_prefix = "PАXLI_TEST_OCR_VALID:"
    assert homoglyph_prefix.encode("utf-8") != b"PAXLI_TEST_OCR_VALID:"
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES + homoglyph_prefix.encode("utf-8") + b"some text\x00"
    )
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_truncated_valid_prefix_is_not_recognized() -> None:
    """A partial prefix (missing its final ':') must not be treated as a
    match -- proves the prefix comparison requires the complete literal,
    not just a leading-substring coincidence."""
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_VALI")
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_empty_payload_between_prefix_and_terminator_is_unreadable() -> None:
    """The valid-prefix immediately followed by the terminator (a zero-
    length payload) is a real adversarial shape, not just the already-
    covered no-terminator-at-all case -- must degrade to UNREADABLE, not
    a VALID result with empty raw/fields."""
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + b"PAXLI_TEST_OCR_VALID:\x00")
    assert result.outcome is OCRReadOutcome.UNREADABLE
    assert result.extraction is None


@pytest.mark.asyncio
async def test_ocr_engine_terminator_at_last_valid_window_byte_is_captured() -> None:
    """Boundary math: a terminator at the last byte still inside the
    truncation window (index MAX_BYTES - 1 relative to the payload start)
    must be found and honored exactly, not off-by-one dropped or
    included."""
    payload = b"B" * 2047
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES
        + b"PAXLI_TEST_OCR_VALID:"
        + payload
        + b"\x00"
        + b"TAIL_MUST_NOT_APPEAR"
    )
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == payload.decode()
    assert "TAIL_MUST_NOT_APPEAR" not in result.extraction.raw


@pytest.mark.asyncio
async def test_ocr_engine_terminator_one_byte_past_window_is_truncated_not_found() -> None:
    """The complementary boundary case: a terminator placed exactly one
    byte past the truncation window is outside the bounded find() range
    and must NOT be treated as found -- the payload instead truncates to
    exactly MAX_BYTES, silently dropping the terminator and everything
    after it, never leaking trailing bytes."""
    payload = b"C" * 2048
    engine = DeterministicOCREngine()
    result = await engine.extract(
        MINIMAL_JPEG_BYTES
        + b"PAXLI_TEST_OCR_VALID:"
        + payload
        + b"\x00"
        + b"TAIL_MUST_NOT_APPEAR"
    )
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == payload.decode()
    assert len(result.extraction.raw) == 2048
    assert "TAIL_MUST_NOT_APPEAR" not in result.extraction.raw


@pytest.mark.asyncio
async def test_ocr_engine_long_mixed_unicode_ascii_payload_round_trips_correctly() -> None:
    """A sustained, well-under-the-limit mix of ASCII and multi-byte
    Unicode field data (the realistic shape of OCR text spanning several
    fields) round-trips exactly -- not just the short adversarial snippet
    covered elsewhere."""
    adversarial_text = (
        "surname=Müller;given_names=François Núñez;"
        "notes=مرحبا 世界 Здравствуй мир こんにちは"
    )
    marker = f"PAXLI_TEST_OCR_VALID:{adversarial_text}\x00".encode()
    engine = DeterministicOCREngine()
    result = await engine.extract(MINIMAL_JPEG_BYTES + marker)
    assert result.outcome is OCRReadOutcome.VALID
    assert result.extraction is not None
    assert result.extraction.raw == adversarial_text
    assert result.extraction.fields["surname"] == "Müller"
    assert result.extraction.fields["given_names"] == "François Núñez"
