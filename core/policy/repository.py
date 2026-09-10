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

    async def add(self, policy: VerificationPolicy) -> VerificationPolicy: ...

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

    async def list_versions(
        self, policy_id: str, tenant_id: str
    ) -> Sequence[VerificationPolicy]: ...
