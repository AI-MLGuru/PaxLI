from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from core.policy.models import VerificationPolicy
from core.verification.enums import AssuranceLevel


class VerificationPolicyRepository(Protocol):
    """No generic update() -- the only mutation this repository permits is
    the narrow, named `mark_superseded` status/timestamp transition
    (Invariant 07: an activated version's CONTENT must never be modified in
    place). A rollback or a new policy submission is always a new row via
    `add`, never a content edit of an existing one."""

    async def add(
        self, policy: VerificationPolicy, idempotency_key: str | None = None
    ) -> VerificationPolicy: ...

    async def mark_superseded(
        self, policy_row_id: UUID, tenant_id: str, superseded_at: datetime
    ) -> None:
        """Flips status ACTIVE -> SUPERSEDED and sets superseded_at on an
        existing row. Touches no other column -- content, hash, version,
        and identity are untouched."""
        ...

    async def get(self, policy_row_id: UUID, tenant_id: str) -> VerificationPolicy | None: ...

    async def get_active(
        self, tenant_id: str, assurance_level: AssuranceLevel
    ) -> VerificationPolicy | None: ...

    async def get_version(
        self, policy_id: str, version: int, tenant_id: str
    ) -> VerificationPolicy | None: ...

    async def get_max_version(self, policy_id: str, tenant_id: str) -> int:
        """Returns 0 if no version of `policy_id` exists yet for the tenant."""
        ...

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationPolicy | None:
        """`idempotency_key` here is the composed, operation-scoped key
        (e.g. "policy_create_and_activate:<caller-key>") -- callers never
        pass a raw caller-supplied key directly, so a reused key can never
        collide across create-and-activate vs. rollback (Invariant-12
        remediation review)."""
        ...

    async def list_versions(
        self, policy_id: str, tenant_id: str
    ) -> Sequence[VerificationPolicy]: ...
