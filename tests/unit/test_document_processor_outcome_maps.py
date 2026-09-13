"""DP-004 §6/§8 / DP-006 §5: _MRZ_OUTCOME_MAP/_BARCODE_OUTCOME_MAP/
_OCR_OUTCOME_MAP encode DP-003 §7 / DP-005 §7's frozen failure-mapping
tables directly as code. Exhaustiveness (every outcome enum member has
an entry) is enforced here, not assumed -- a future new outcome member
added to MRZReadOutcome/BarcodeReadOutcome/OCRReadOutcome without a
corresponding map entry would raise a KeyError at runtime in
_run_mrz/_run_barcode/_run_ocr; this test catches that at commit time
instead.

Pure data-structure tests, no DB/session dependency -- infrastructure.
document.processor's own module docstring notes it has "no fake-
repository seam to unit-test against" for its orchestration behavior,
but these dicts are plain data and need no such seam.
"""

from core.document.types import BarcodeReadOutcome, MRZReadOutcome, OCRReadOutcome
from core.evidence_result.enums import EvidenceResultStatus
from infrastructure.document.processor import (
    _BARCODE_OUTCOME_MAP,
    _MRZ_OUTCOME_MAP,
    _OCR_OUTCOME_MAP,
)


def test_mrz_outcome_map_is_exhaustive() -> None:
    for outcome in MRZReadOutcome:
        assert outcome in _MRZ_OUTCOME_MAP, f"{outcome} has no entry in _MRZ_OUTCOME_MAP"


def test_barcode_outcome_map_is_exhaustive() -> None:
    for outcome in BarcodeReadOutcome:
        assert outcome in _BARCODE_OUTCOME_MAP, f"{outcome} has no entry in _BARCODE_OUTCOME_MAP"


def test_mrz_outcome_map_matches_dp003_frozen_table() -> None:
    assert _MRZ_OUTCOME_MAP[MRZReadOutcome.UNREADABLE][0] is EvidenceResultStatus.INCONCLUSIVE
    assert _MRZ_OUTCOME_MAP[MRZReadOutcome.MALFORMED][0] is EvidenceResultStatus.INCONCLUSIVE
    assert _MRZ_OUTCOME_MAP[MRZReadOutcome.CHECK_DIGIT_MISMATCH][0] is EvidenceResultStatus.FAIL
    assert _MRZ_OUTCOME_MAP[MRZReadOutcome.VALID] == (EvidenceResultStatus.PASS, None)


def test_barcode_outcome_map_matches_dp003_frozen_table() -> None:
    assert (
        _BARCODE_OUTCOME_MAP[BarcodeReadOutcome.UNREADABLE][0] is EvidenceResultStatus.INCONCLUSIVE
    )
    assert (
        _BARCODE_OUTCOME_MAP[BarcodeReadOutcome.PAYLOAD_UNRECOGNIZED][0]
        is EvidenceResultStatus.INCONCLUSIVE
    )
    assert (
        _BARCODE_OUTCOME_MAP[BarcodeReadOutcome.PAYLOAD_MALFORMED][0]
        is EvidenceResultStatus.INCONCLUSIVE
    )
    assert _BARCODE_OUTCOME_MAP[BarcodeReadOutcome.VALID] == (EvidenceResultStatus.PASS, None)


def test_no_barcode_outcome_ever_maps_to_fail() -> None:
    """DP-003 Decision 2: BARCODE_QR MUST NOT emit FAIL in Phase 2 --
    asserted directly against the map, not inferred from an absence of
    counter-examples."""
    mapped_statuses = {status for status, _reason in _BARCODE_OUTCOME_MAP.values()}
    assert EvidenceResultStatus.FAIL not in mapped_statuses


def test_ocr_outcome_map_is_exhaustive() -> None:
    for outcome in OCRReadOutcome:
        assert outcome in _OCR_OUTCOME_MAP, f"{outcome} has no entry in _OCR_OUTCOME_MAP"


def test_ocr_outcome_map_matches_dp005_frozen_table() -> None:
    assert _OCR_OUTCOME_MAP[OCRReadOutcome.UNREADABLE][0] is EvidenceResultStatus.INCONCLUSIVE
    assert _OCR_OUTCOME_MAP[OCRReadOutcome.VALID] == (EvidenceResultStatus.PASS, None)


def test_no_ocr_outcome_ever_maps_to_fail() -> None:
    """DP-005 Decision 2: OCR_EXTRACTION MUST NOT emit FAIL in Phase 3 --
    asserted directly against the map, not inferred from an absence of
    counter-examples."""
    mapped_statuses = {status for status, _reason in _OCR_OUTCOME_MAP.values()}
    assert EvidenceResultStatus.FAIL not in mapped_statuses
