"""DP-008/DP-009 Phase 4: FieldReconciliationResult.__post_init__ enforces
its two frozen invariants (DP-008 §3.5) as real runtime checks, not just
documentation -- confirmed here directly rather than assumed."""

import pytest

from core.document.types import FieldReconciliationResult


def _result(**overrides: object) -> FieldReconciliationResult:
    fields: dict[str, object] = {
        "full_name": None,
        "surname": None,
        "given_names": None,
        "date_of_birth": None,
        "sex": None,
        "document_number": None,
        "nationality": None,
        "expiry_date": None,
        "extensions": {},
        "conflicted_fields": (),
    }
    fields.update(overrides)
    return FieldReconciliationResult(**fields)  # type: ignore[arg-type]


def test_construction_with_no_conflicts_succeeds() -> None:
    result = _result(full_name="ANNA MARIA ERIKSSON")
    assert result.conflicted_fields == ()


def test_construction_with_a_listed_field_correctly_null_succeeds() -> None:
    result = _result(date_of_birth=None, conflicted_fields=("date_of_birth",))
    assert result.conflicted_fields == ("date_of_birth",)
    assert result.date_of_birth is None


def test_conflicted_fields_containing_a_non_canonical_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-canonical"):
        _result(conflicted_fields=("extensions",))


def test_conflicted_fields_listing_a_field_whose_value_is_not_null_is_rejected() -> None:
    """DP-008 §3.5's one-directional invariant: a listed field MUST be
    null. Constructing a result that lists a populated field is exactly
    the violation this check exists to catch."""
    with pytest.raises(ValueError, match="not null"):
        _result(date_of_birth="1990-01-01", conflicted_fields=("date_of_birth",))
