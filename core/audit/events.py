from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor: str
    occurred_at: datetime
    resource_id: str

    @classmethod
    def now(cls, event_type: str, actor: str, resource_id: str) -> "AuditEvent":
        return cls(event_type, actor, datetime.now(timezone.utc), resource_id)
