"""Requirement traceability: EVD-3.26.*, EVD-3.27.*, PRV-11.29.*, PRV-11.30.*,
PRV-11.35.*, Invariant 06 remediation Phase 4 (HTTP/API)."""

from uuid import UUID, uuid4

from core.audit.service import AuditService
from core.evidence_result.enums import EvidenceResultStatus, EvidenceResultType
from core.evidence_result.service import EvidenceResultService
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from tests.conftest import MINIMAL_JPEG_BYTES

_DELETED_RESPONSE_KEYS = {"code", "message", "category", "request_id"}


def _create_session(api_client, token: str) -> str:
    response = api_client.post(
        "/v1/verification-sessions",
        json={"assurance_level": "STANDARD"},
        headers={"Authorization": token},
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _upload_selfie(api_client, token: str, session_id: str) -> dict:
    response = api_client.post(
        f"/v1/verification-sessions/{session_id}/selfie",
        files={"file": ("selfie.jpg", MINIMAL_JPEG_BYTES + b"CANARY_DELETE_ME", "image/jpeg")},
        headers={"Authorization": token},
    )
    assert response.status_code == 201
    return response.json()


def _delete_evidence(api_client, token: str, session_id: str, evidence_id: str, **kwargs):
    return api_client.request(
        "DELETE",
        f"/v1/verification-sessions/{session_id}/evidence/{evidence_id}",
        json={"deletion_basis": "TENANT_REQUEST", **kwargs},
        headers={"Authorization": token},
    )


def test_admin_can_delete_evidence(api_client, issued_credentials, raw_storage) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    assert len(raw_storage.blobs) == 1

    response = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, evidence["id"]
    )
    assert response.status_code == 204
    assert raw_storage.blobs == {}


def test_deleted_evidence_returns_410_not_404(api_client, issued_credentials) -> None:
    """Invariant-06 firm choice: a deleted evidence ID must remain
    distinguishable from one that never existed."""
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    delete_response = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, evidence["id"]
    )
    assert delete_response.status_code == 204

    get_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence/{evidence['id']}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert get_response.status_code == 410
    body = get_response.json()
    assert set(body.keys()) == _DELETED_RESPONSE_KEYS
    assert body["code"] == "EVIDENCE_DELETED"
    assert body["category"] == "NOT_FOUND"
    # No deletion metadata leaks into the response body (basis, actor,
    # timestamps, object key, checksum).
    serialized = str(body)
    for leaked in ("TENANT_REQUEST", "admin", session_id, evidence["checksum"]):
        assert leaked not in serialized


def test_never_created_evidence_returns_ordinary_404(api_client, issued_credentials) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    response = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence/{uuid4()}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 404


def test_cross_tenant_deleted_evidence_is_ordinary_404_not_410(
    api_client, issued_credentials
) -> None:
    """A deleted-evidence tombstone must not become a cross-tenant
    existence oracle: another tenant probing the same ID sees an ordinary
    404, identical to "never existed", never the 410 reserved for the
    owning tenant."""
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_b_operational"], session_id)
    delete_response = _delete_evidence(
        api_client, issued_credentials["tenant_b_admin"], session_id, evidence["id"]
    )
    assert delete_response.status_code == 204

    cross_tenant_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence/{evidence['id']}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert cross_tenant_response.status_code == 404


def test_deleted_evidence_is_excluded_from_list(api_client, issued_credentials) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    kept = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    deleted = api_client.post(
        f"/v1/verification-sessions/{session_id}/document",
        files={"file": ("doc.jpg", MINIMAL_JPEG_BYTES + b"CANARY_LIST_DELETE", "image/jpeg")},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    ).json()
    delete_response = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, deleted["id"]
    )
    assert delete_response.status_code == 204

    list_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    ids = {item["id"] for item in list_response.json()["data"]}
    assert ids == {kept["id"]}


def test_operational_credential_cannot_delete_evidence(api_client, issued_credentials) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    response = _delete_evidence(
        api_client, issued_credentials["tenant_a_operational"], session_id, evidence["id"]
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTHORIZATION_DENIED"


def test_cross_tenant_delete_attempt_is_404(api_client, issued_credentials) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_b_operational"], session_id)
    response = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, evidence["id"]
    )
    assert response.status_code == 404


def test_delete_nonexistent_evidence_is_404(api_client, issued_credentials) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    response = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, str(uuid4())
    )
    assert response.status_code == 404


def test_other_authorized_basis_without_reference_is_rejected(
    api_client, issued_credentials
) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    response = _delete_evidence(
        api_client,
        issued_credentials["tenant_a_admin"],
        session_id,
        evidence["id"],
        deletion_basis="OTHER_AUTHORIZED_BASIS",
    )
    assert response.status_code == 400


async def _create_evidence_result(
    session_factory, *, tenant_id: str, session_id: UUID, source_reference: UUID | None = None
):
    key_provider = LocalAesGcmKeyProvider({"test-evidence-key": b"0" * 32})
    async with session_factory() as session:
        service = EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-key"),
            AuditService(SqlAlchemyAuditEventRepository(session)),
            SqlAlchemyEvidenceRepository(session),
        )
        result = await service.create(
            tenant_id=tenant_id,
            session_id=session_id,
            evidence_type=EvidenceResultType.FACE_MATCH,
            status=EvidenceResultStatus.PASS,
            producer="test-producer",
            producer_version="1.0",
            result={"similarity": 0.9},
            source_reference=source_reference,
        )
        await session.commit()
        return result


async def test_delete_evidence_with_dependent_result_is_409(
    api_client, issued_credentials, session_factory
) -> None:
    """Phase 6 finding: a foreign key with no ON DELETE behavior
    (EvidenceResult.source_reference -> Evidence.id) means the request must
    be rejected up front, not allowed to reach a permanently stuck
    reconciliation with the storage object already gone."""
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    await _create_evidence_result(
        session_factory,
        tenant_id="tenant-a",
        session_id=UUID(session_id),
        source_reference=UUID(evidence["id"]),
    )

    response = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, evidence["id"]
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DELETION_BLOCKED_BY_DEPENDENTS"

    # Confirm nothing was touched: evidence still retrievable, live.
    get_response = api_client.get(
        f"/v1/verification-sessions/{session_id}/evidence/{evidence['id']}",
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert get_response.status_code == 200


async def test_admin_can_delete_evidence_result(
    api_client, issued_credentials, session_factory
) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    result = await _create_evidence_result(
        session_factory, tenant_id="tenant-a", session_id=UUID(session_id)
    )

    response = api_client.request(
        "DELETE",
        f"/v1/management/evidence-results/{result.id}",
        json={"deletion_basis": "TENANT_REQUEST"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert response.status_code == 204

    async with session_factory() as session:
        key_provider = LocalAesGcmKeyProvider({"test-evidence-key": b"0" * 32})
        repo = SqlAlchemyEvidenceResultRepository(session, key_provider, "test-evidence-key")
        assert await repo.get(result.id, "tenant-a") is None
        tombstone = await repo.get_tombstone(result.id, "tenant-a")
        assert tombstone is not None
        assert tombstone.executed_at is not None


async def test_operational_credential_cannot_delete_evidence_result(
    api_client, issued_credentials, session_factory
) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    result = await _create_evidence_result(
        session_factory, tenant_id="tenant-a", session_id=UUID(session_id)
    )

    response = api_client.request(
        "DELETE",
        f"/v1/management/evidence-results/{result.id}",
        json={"deletion_basis": "TENANT_REQUEST"},
        headers={"Authorization": issued_credentials["tenant_a_operational"]},
    )
    assert response.status_code == 403


async def test_cross_tenant_evidence_result_delete_attempt_is_404(
    api_client, issued_credentials, session_factory
) -> None:
    session_id = _create_session(api_client, issued_credentials["tenant_b_operational"])
    result = await _create_evidence_result(
        session_factory, tenant_id="tenant-b", session_id=UUID(session_id)
    )

    response = api_client.request(
        "DELETE",
        f"/v1/management/evidence-results/{result.id}",
        json={"deletion_basis": "TENANT_REQUEST"},
        headers={"Authorization": issued_credentials["tenant_a_admin"]},
    )
    assert response.status_code == 404


def test_deletion_is_idempotently_retryable(api_client, issued_credentials) -> None:
    """A repeated DELETE against an already-deleted evidence_id must
    succeed safely rather than erroring (Invariant-06 remediation: the
    request phase replays the existing tombstone, and reconciliation
    short-circuits on an already-executed tombstone)."""
    session_id = _create_session(api_client, issued_credentials["tenant_a_operational"])
    evidence = _upload_selfie(api_client, issued_credentials["tenant_a_operational"], session_id)
    first = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, evidence["id"]
    )
    second = _delete_evidence(
        api_client, issued_credentials["tenant_a_admin"], session_id, evidence["id"]
    )
    assert first.status_code == second.status_code == 204
