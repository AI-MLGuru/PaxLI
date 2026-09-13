"""Real ICAO Doc 9303 TD3 (passport) machine-readable-zone structural
parsing and check-digit validation -- DP-003 Decision 8: this logic is
real, not a deterministic stand-in. Kept in its own module, separate
from core.document.deterministic's explicitly non-representative test
doubles, so the real ICAO 9303 logic reads as what it is, not bundled
inside a file whose other contents are deliberately fake.

TD3 is the only format required by the frozen V1 document catalog
(DP-001 Decision 5 -- only ICAO_PASSPORT_DATA_PAGE is MRZ-bearing).
TD1/TD2 support is not required and is not implemented, but nothing
here precludes adding it later.

Structural parsing (parse_icao9303_structure) and check-digit validation
(validate_check_digits) are deliberately separate steps: the former is
the MRZReadOutcome.MALFORMED boundary (does this even look like a TD3
MRZ), the latter is the MRZReadOutcome.CHECK_DIGIT_MISMATCH boundary
(is the data internally consistent) -- DP-003 Decision 1 requires these
stay distinguishable, never collapsed into one check.
"""

from dataclasses import dataclass

_LINE_LENGTH = 44
_WEIGHTS = (7, 3, 1)


def _char_value(char: str) -> int:
    if char == "<":
        return 0
    if char.isdigit():
        return int(char)
    if "A" <= char <= "Z":
        return ord(char) - ord("A") + 10
    raise ValueError(f"character {char!r} is not valid in an ICAO 9303 MRZ field")


def _compute_check_digit(data: str) -> int:
    """ICAO 9303's weighted 7-3-1 modulo-10 algorithm, cycling per
    character position."""
    total = 0
    for index, char in enumerate(data):
        total += _char_value(char) * _WEIGHTS[index % 3]
    return total % 10


def _check_digit_matches(data: str, check_digit: str) -> bool:
    if check_digit == "<":
        expected = 0
    elif check_digit.isdigit():
        expected = int(check_digit)
    else:
        return False
    try:
        return _compute_check_digit(data) == expected
    except ValueError:
        return False


@dataclass(frozen=True)
class ParsedMRZTD3:
    """Structural parse result for one TD3 (passport) MRZ -- two
    44-character lines. `fields` is what MRZExtraction.fields is built
    from (core.document.deterministic); the four *_check_digit_valid
    flags are what validate_check_digits() reduces to a single bool."""

    document_type: str
    issuing_state: str
    surname: str
    given_names: str
    document_number: str
    nationality: str
    date_of_birth: str
    sex: str
    date_of_expiry: str
    personal_number: str
    document_number_check_digit_valid: bool
    date_of_birth_check_digit_valid: bool
    date_of_expiry_check_digit_valid: bool
    composite_check_digit_valid: bool

    @property
    def fields(self) -> dict[str, str]:
        return {
            "document_type": self.document_type,
            "issuing_state": self.issuing_state,
            "surname": self.surname,
            "given_names": self.given_names,
            "document_number": self.document_number,
            "nationality": self.nationality,
            "date_of_birth": self.date_of_birth,
            "sex": self.sex,
            "date_of_expiry": self.date_of_expiry,
            "personal_number": self.personal_number,
        }


def parse_icao9303_structure(raw: str) -> ParsedMRZTD3 | None:
    """Structurally parses a two-line, 44-character-per-line TD3 MRZ.
    Accepts either an embedded newline between the two lines or one
    continuous 88-character string. Returns None if `raw` doesn't
    conform to TD3's fixed format at all -- wrong length/line count, a
    character outside the permitted A-Z/0-9/< set anywhere, a missing
    name separator, or a non-numeric date field. Check-digit validity is
    intentionally NOT evaluated here -- see validate_check_digits()."""
    lines = raw.split("\n", 1) if "\n" in raw else [raw[:_LINE_LENGTH], raw[_LINE_LENGTH:]]
    if len(lines) != 2 or len(lines[0]) != _LINE_LENGTH or len(lines[1]) != _LINE_LENGTH:
        return None
    line1, line2 = lines

    try:
        for char in line1 + line2:
            _char_value(char)
    except ValueError:
        return None

    if line1[0:2] not in ("P<", "P "):
        return None
    issuing_state = line1[2:5]
    name_field = line1[5:44]
    if "<<" not in name_field:
        return None
    surname_raw, given_raw = name_field.split("<<", 1)
    surname = surname_raw.replace("<", " ").strip()
    given_names = given_raw.replace("<", " ").strip()

    document_number = line2[0:9]
    document_number_check = line2[9]
    nationality = line2[10:13]
    date_of_birth = line2[13:19]
    date_of_birth_check = line2[19]
    sex = line2[20]
    date_of_expiry = line2[21:27]
    date_of_expiry_check = line2[27]
    personal_number = line2[28:42]
    personal_number_check = line2[42]
    composite_check = line2[43]

    if not date_of_birth.isdigit() or not date_of_expiry.isdigit():
        return None

    composite_data = (
        document_number
        + document_number_check
        + date_of_birth
        + date_of_birth_check
        + date_of_expiry
        + date_of_expiry_check
        + personal_number
        + personal_number_check
    )

    return ParsedMRZTD3(
        document_type=line1[0:2].rstrip("<"),
        issuing_state=issuing_state,
        surname=surname,
        given_names=given_names,
        document_number=document_number.rstrip("<"),
        nationality=nationality,
        date_of_birth=date_of_birth,
        sex=sex if sex in ("M", "F") else "UNSPECIFIED",
        date_of_expiry=date_of_expiry,
        personal_number=personal_number.rstrip("<"),
        document_number_check_digit_valid=_check_digit_matches(
            document_number, document_number_check
        ),
        date_of_birth_check_digit_valid=_check_digit_matches(date_of_birth, date_of_birth_check),
        date_of_expiry_check_digit_valid=_check_digit_matches(date_of_expiry, date_of_expiry_check),
        composite_check_digit_valid=_check_digit_matches(composite_data, composite_check),
    )


def validate_check_digits(parsed: ParsedMRZTD3) -> bool:
    """True only if every individual check digit (document number, date
    of birth, date of expiry) AND the composite check digit all
    validate -- any single mismatch makes the whole MRZ
    CHECK_DIGIT_MISMATCH, not just the one field."""
    return (
        parsed.document_number_check_digit_valid
        and parsed.date_of_birth_check_digit_valid
        and parsed.date_of_expiry_check_digit_valid
        and parsed.composite_check_digit_valid
    )
