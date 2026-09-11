"""DE-003 §11 / Amendment B: the defensive fallback for duplicate effective
evidence. Unit-tested with in-memory domain objects deliberately -- real
Postgres integration coverage (test_one_effective_per_type_index_rejects_
two_effective_rows_direct_insert) already proves the primary invariant
(the partial unique index) makes this state unreachable through the
repository; this module's defensive logic can only be exercised by
constructing the pathological input directly, bypassing persistence.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.evidence_result.effective import resolve_one_effective_per_type
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.models import EvidenceResult


def _result(
    evidence_type: EvidenceResultType, *, produced_at: datetime, integrity_reference: str
) -> EvidenceResult:
    return EvidenceResult(
        tenant_id="tenant-a",
        session_id=uuid4(),
        evidence_type=evidence_type,
        status=EvidenceResultStatus.PASS,
        producer="p",
        producer_version="1",
        produced_at=produced_at,
        persisted_at=produced_at,
        integrity_reference=integrity_reference,
    )


def test_single_candidate_per_type_passes_through_unchanged() -> None:
    now = datetime.now(UTC)
    a = _result(EvidenceResultType.FACE_MATCH, produced_at=now, integrity_reference="a")
    b = _result(EvidenceResultType.DOCUMENT_QUALITY, produced_at=now, integrity_reference="b")
    resolved = resolve_one_effective_per_type([a, b])
    assert {r.id for r in resolved} == {a.id, b.id}


def test_duplicate_type_resolves_to_most_recently_produced() -> None:
    older = _result(
        EvidenceResultType.FACE_MATCH,
        produced_at=datetime.now(UTC) - timedelta(seconds=5),
        integrity_reference="older",
    )
    newer = _result(
        EvidenceResultType.FACE_MATCH, produced_at=datetime.now(UTC), integrity_reference="newer"
    )
    resolved = resolve_one_effective_per_type([older, newer])
    assert len(resolved) == 1
    assert resolved[0].id == newer.id


def test_tied_produced_at_breaks_deterministically_on_id_not_list_order() -> None:
    """Amendment B's exact wording: 'every fallback selection must have a
    total ordering... never rely on database row order.'"""
    tied_at = datetime.now(UTC)
    a = _result(EvidenceResultType.FACE_MATCH, produced_at=tied_at, integrity_reference="a")
    b = _result(EvidenceResultType.FACE_MATCH, produced_at=tied_at, integrity_reference="b")
    expected_winner = max(a, b, key=lambda r: r.id)

    forward = resolve_one_effective_per_type([a, b])
    reversed_order = resolve_one_effective_per_type([b, a])
    assert forward[0].id == reversed_order[0].id == expected_winner.id


def test_duplicate_detection_emits_a_warning_signal(caplog) -> None:
    """The fallback must not silently normalize corrupted state -- it must
    surface an operational integrity signal every time it is exercised."""
    tied_at = datetime.now(UTC)
    a = _result(EvidenceResultType.FACE_MATCH, produced_at=tied_at, integrity_reference="a")
    b = _result(EvidenceResultType.FACE_MATCH, produced_at=tied_at, integrity_reference="b")

    with caplog.at_level(logging.WARNING):
        resolve_one_effective_per_type([a, b])

    assert any("duplicate_effective_evidence_detected" in r.message for r in caplog.records)


def test_no_candidates_resolves_to_empty() -> None:
    assert resolve_one_effective_per_type([]) == []
