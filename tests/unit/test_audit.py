from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.audit.enums import AuditDurability, AuditEventType, AuditStatus
from core.audit.models import AuditEvent
from core.audit.service import AuditPersistenceError, AuditService, sanitize_metadata


class FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []
        self.fail = False

    async def add(self, event: AuditEvent, dedupe_key: str | None = None) -> AuditEvent:
        if self.fail:
            raise RuntimeError("database unavailable")
        if dedupe_key:
            for existing in self.events:
                if existing.metadata.get("dedupe_key") == dedupe_key:
                    return existing
        event.metadata["dedupe_key"] = dedupe_key
        self.events.append(event)
        return event

    async def get_by_dedupe_key(
        self, tenant_id: str, session_id: UUID | None, dedupe_key: str
    ) -> AuditEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.tenant_id == tenant_id
                and event.session_id == session_id
                and event.metadata.get("dedupe_key") == dedupe_key
            ),
            None,
        )

    async def list_for_session(self, session_id: UUID, tenant_id: str) -> list[AuditEvent]:
        return sorted(
            [
                event
                for event in self.events
                if event.session_id == session_id and event.tenant_id == tenant_id
            ],
            key=lambda event: event.occurred_at,
        )


def test_sanitize_metadata_redacts_sensitive_values_and_binary_payloads() -> None:
    result = sanitize_metadata(
        {
            "access_token": "secret-token",
            "document_image": b"raw-document",
            "nested": {"password": "secret", "safe": "value"},
            "long": "x" * 600,
        }
    )
    assert result["access_token"] == "[REDACTED]"
    assert result["document_image"] == "[REDACTED]"
    assert result["nested"]["password"] == "[REDACTED]"
    assert result["nested"]["safe"] == "value"
    assert len(result["long"]) == 512


@pytest.mark.asyncio
async def test_required_audit_failure_is_not_silent() -> None:
    repository = FakeAuditRepository()
    repository.fail = True
    service = AuditService(repository)

    with pytest.raises(AuditPersistenceError):
        await service.record(
            tenant_id="tenant-a",
            session_id=uuid4(),
            event_type=AuditEventType.SESSION_CREATED,
            component="test",
            action="create",
            status=AuditStatus.SUCCESS,
        )


@pytest.mark.asyncio
async def test_best_effort_audit_failure_returns_event() -> None:
    repository = FakeAuditRepository()
    repository.fail = True
    service = AuditService(repository)

    event = await service.record(
        tenant_id="tenant-a",
        event_type=AuditEventType.EVIDENCE_RETRIEVED,
        component="test",
        action="retrieve",
        status=AuditStatus.SUCCESS,
        durability=AuditDurability.BEST_EFFORT,
    )

    assert event.tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_audit_event_order_and_tenant_session_isolation() -> None:
    repository = FakeAuditRepository()
    service = AuditService(repository)
    session_id = uuid4()
    first = datetime.now(UTC)

    await service.record(
        tenant_id="tenant-a",
        session_id=session_id,
        event_type=AuditEventType.SESSION_CREATED,
        component="test",
        action="create",
        status=AuditStatus.SUCCESS,
        metadata={"occurred": first.isoformat()},
    )
    await service.record(
        tenant_id="tenant-a",
        session_id=session_id,
        event_type=AuditEventType.EVIDENCE_UPLOADED,
        component="test",
        action="upload",
        status=AuditStatus.SUCCESS,
    )
    await service.record(
        tenant_id="tenant-b",
        session_id=session_id,
        event_type=AuditEventType.SESSION_CREATED,
        component="test",
        action="create",
        status=AuditStatus.SUCCESS,
    )

    events = await repository.list_for_session(session_id, "tenant-a")
    assert [event.event_type for event in events] == [
        AuditEventType.SESSION_CREATED,
        AuditEventType.EVIDENCE_UPLOADED,
    ]
    assert all(event.tenant_id == "tenant-a" for event in events)


@pytest.mark.asyncio
async def test_duplicate_dedupe_key_replays_event() -> None:
    repository = FakeAuditRepository()
    service = AuditService(repository)
    session_id = uuid4()

    first = await service.record(
        tenant_id="tenant-a",
        session_id=session_id,
        event_type=AuditEventType.SESSION_CREATED,
        component="test",
        action="create",
        status=AuditStatus.SUCCESS,
        dedupe_key="request-1",
    )
    replay = await service.record(
        tenant_id="tenant-a",
        session_id=session_id,
        event_type=AuditEventType.SESSION_CREATED,
        component="test",
        action="create",
        status=AuditStatus.SUCCESS,
        dedupe_key="request-1",
    )

    assert replay.event_id == first.event_id
    assert len(repository.events) == 1
