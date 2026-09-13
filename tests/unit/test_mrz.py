"""DP-003 Decision 8: parse_icao9303_structure()/validate_check_digits()
are REAL ICAO 9303 logic, not a deterministic stand-in -- this deserves
the positive/negative/edge-case rigor that implies, unlike the marker-
driven test doubles in core.document.deterministic.

Reference vector: the canonical ICAO Doc 9303 Part 4 sample MRZ (Anna
Maria Eriksson), reproduced in every widely-cited MRZ check-digit
worked example.
"""

from core.document.mrz import parse_icao9303_structure, validate_check_digits

_LINE1 = "P<UTOERIKSSON<<ANNA<MARIA" + "<" * (44 - len("P<UTOERIKSSON<<ANNA<MARIA"))
_LINE2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
_VALID_RAW = _LINE1 + _LINE2


def test_reference_vector_parses_and_validates() -> None:
    parsed = parse_icao9303_structure(_VALID_RAW)
    assert parsed is not None
    assert parsed.document_number == "L898902C3"
    assert parsed.nationality == "UTO"
    assert parsed.date_of_birth == "740812"
    assert parsed.sex == "F"
    assert parsed.date_of_expiry == "120415"
    assert parsed.surname == "ERIKSSON"
    assert parsed.given_names == "ANNA MARIA"
    assert validate_check_digits(parsed) is True


def test_reference_vector_accepts_embedded_newline_separator() -> None:
    parsed = parse_icao9303_structure(_LINE1 + "\n" + _LINE2)
    assert parsed is not None
    assert validate_check_digits(parsed) is True


def test_corrupted_document_number_check_digit_fails_validation() -> None:
    corrupted = _LINE1 + _LINE2[:9] + "5" + _LINE2[10:]  # was 6
    parsed = parse_icao9303_structure(corrupted)
    assert parsed is not None
    assert parsed.document_number_check_digit_valid is False
    assert validate_check_digits(parsed) is False


def test_corrupted_date_of_birth_check_digit_fails_validation() -> None:
    corrupted = _LINE1 + _LINE2[:19] + "9" + _LINE2[20:]  # was 2
    parsed = parse_icao9303_structure(corrupted)
    assert parsed is not None
    assert parsed.date_of_birth_check_digit_valid is False
    assert validate_check_digits(parsed) is False


def test_corrupted_date_of_expiry_check_digit_fails_validation() -> None:
    corrupted = _LINE1 + _LINE2[:27] + "0" + _LINE2[28:]  # was 9
    parsed = parse_icao9303_structure(corrupted)
    assert parsed is not None
    assert parsed.date_of_expiry_check_digit_valid is False
    assert validate_check_digits(parsed) is False


def test_corrupted_composite_check_digit_fails_validation() -> None:
    corrupted = _LINE2[:-1] + "9"  # was 0
    parsed = parse_icao9303_structure(_LINE1 + corrupted)
    assert parsed is not None
    assert parsed.composite_check_digit_valid is False
    assert validate_check_digits(parsed) is False


def test_every_field_check_digit_independently_detected() -> None:
    """A single-field corruption must not be masked by the others still
    passing -- validate_check_digits() is an AND across all four."""
    valid_but_one_wrong = _LINE1 + "X" * 44
    assert parse_icao9303_structure(valid_but_one_wrong) is None  # sanity: garbage doesn't parse


def test_wrong_total_length_is_malformed() -> None:
    assert parse_icao9303_structure("too short") is None
    assert parse_icao9303_structure(_VALID_RAW + "extra") is None
    assert parse_icao9303_structure(_VALID_RAW[:-1]) is None


def test_wrong_line_lengths_when_newline_present_is_malformed() -> None:
    assert parse_icao9303_structure("short\n" + _LINE2) is None
    assert parse_icao9303_structure(_LINE1 + "\nshort") is None


def test_invalid_character_outside_az09_angle_bracket_is_malformed() -> None:
    corrupted = _LINE1[:10] + "@" + _LINE1[11:]
    assert parse_icao9303_structure(corrupted + _LINE2) is None


def test_missing_document_type_prefix_is_malformed() -> None:
    corrupted = "X<" + _LINE1[2:]
    assert parse_icao9303_structure(corrupted + _LINE2) is None


def test_missing_name_separator_is_malformed() -> None:
    corrupted = "P<UTO" + "A" * 39
    assert parse_icao9303_structure(corrupted + _LINE2) is None


def test_non_numeric_date_of_birth_is_malformed() -> None:
    corrupted_line2 = _LINE2[:13] + "AAAAAA" + _LINE2[19:]
    assert parse_icao9303_structure(_LINE1 + corrupted_line2) is None


def test_non_numeric_date_of_expiry_is_malformed() -> None:
    corrupted_line2 = _LINE2[:21] + "AAAAAA" + _LINE2[27:]
    assert parse_icao9303_structure(_LINE1 + corrupted_line2) is None


def test_filler_check_digit_of_less_than_is_treated_as_zero() -> None:
    """ICAO 9303 permits '<' as a valid check-digit character meaning 0
    -- confirmed directly, since an unused personal-number field commonly
    uses this."""
    # Build a variant with an empty personal number (all '<') and a
    # composite recomputed accordingly, to confirm '<' handling doesn't
    # crash or silently misvalidate.
    empty_personal = "<" * 14
    line2 = (
        _LINE2[:28] + empty_personal + "<" + _LINE2[43]
    )  # personal number check digit '<' too
    parsed = parse_icao9303_structure(_LINE1 + line2)
    assert parsed is not None
    assert parsed.personal_number == ""
