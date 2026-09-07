from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.verification.enums import (
    VALID_STATUS_TRANSITIONS,
    AssuranceLevel,
    VerificationStatus,
)


class VerificationSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    external_reference: str | None = None
    status: VerificationStatus = VerificationStatus.CREATED
    assurance_level: AssuranceLevel = AssuranceLevel.STANDARD
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30)
    )
    completed_at: datetime | None = None

    def transition_to(self, status: VerificationStatus) -> None:
        if status not in VALID_STATUS_TRANSITIONS[self.status]:
            raise ValueError(f"Invalid session transition: {self.status} -> {status}")
        self.status = status
        if status in {
            VerificationStatus.VERIFIED,
            VerificationStatus.REJECTED,
            VerificationStatus.REVIEW_REQUIRED,
            VerificationStatus.INCONCLUSIVE,
            VerificationStatus.EXPIRED,
            VerificationStatus.CANCELLED,
        }:
            self.completed_at = datetime.now(UTC)

    def expire_if_needed(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if (
            self.status in {VerificationStatus.CREATED, VerificationStatus.PROCESSING}
            and current_time >= expires_at
        ):
            self.transition_to(VerificationStatus.EXPIRED)
            return True
        return False

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        external_reference: str | None,
        assurance_level: AssuranceLevel,
        ttl_minutes: int,
    ) -> "VerificationSession":
        now = datetime.now(UTC)
        return cls(
            tenant_id=tenant_id,
            external_reference=external_reference,
            assurance_level=assurance_level,
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
