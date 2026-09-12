from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.verification.enums import (
    PRE_PROCESSING_STATUSES,
    TERMINAL_STATUSES,
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
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30))
    completed_at: datetime | None = None
    # DE-002/DE-003 §1 early policy binding: resolved once at creation via
    # PolicyService.get_active() and never re-resolved (VerificationSession.
    # create() below makes all three required together). Optional here, not
    # on the factory, purely for backward compatibility with rows persisted
    # before this field existed -- the same "nullable at the model boundary,
    # required for every new row going forward" discipline this session's
    # migrations have already used repeatedly.
    policy_id: str | None = None
    policy_version: int | None = None
    policy_hash: str | None = None
    # WF-001 §10: the canonical fingerprint of the request that created
    # this session -- sha256(canonical_json({tenant_id, assurance_level,
    # external_reference})), set once at create() and never recomputed.
    # Nullable here for the same migration-safety reason as the policy
    # triple above (rows created before this field existed have none);
    # every new session going forward always has one.
    fingerprint: str | None = None

    def transition_to(self, status: VerificationStatus) -> None:
        if status not in VALID_STATUS_TRANSITIONS[self.status]:
            raise ValueError(f"Invalid session transition: {self.status} -> {status}")
        self.status = status
        if status in TERMINAL_STATUSES:
            self.completed_at = datetime.now(UTC)

    def expire_if_needed(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if self.status in PRE_PROCESSING_STATUSES and current_time >= expires_at:
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
        policy_id: str,
        policy_version: int,
        policy_hash: str,
        fingerprint: str,
    ) -> "VerificationSession":
        """The policy_id/version/hash triple is required here, unlike on
        the bare model fields above: every NEW session must carry a pin
        (DE-002 §1), resolved by the caller (VerificationSessionService)
        before this factory is ever invoked. This is the one and only place
        a session's pin is ever set -- there is no corresponding
        transition/update path, matching Invariant 07's "never re-resolve"
        rule for early binding. `fingerprint` (WF-001 §10) is likewise
        required here: the caller has already computed it from the exact
        same request fields passed above, and this factory does not
        recompute it -- keeping fingerprint computation in exactly one
        place (VerificationSessionService.create())."""
        now = datetime.now(UTC)
        return cls(
            tenant_id=tenant_id,
            external_reference=external_reference,
            assurance_level=assurance_level,
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
            policy_id=policy_id,
            policy_version=policy_version,
            policy_hash=policy_hash,
            fingerprint=fingerprint,
        )
