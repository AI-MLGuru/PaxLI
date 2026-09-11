"""DE-003 §12: the two reference value objects a decision carries.

Both are deliberately *snapshots*, not live pointers. `EvidenceReference` is
the Phase-6 FK lesson applied in advance (DE-002 landmine 1): evidence may be
legitimately deleted after a decision consumed it (retention expiry, an
erasure request), and neither PRV-11.35.3 ("erasure MUST NOT fabricate
historical states") nor DEC-5.30.4 ("historical decisions MUST NOT be
silently overwritten") tolerates a decision that either blocks that deletion
or mutates when it happens. The snapshot fields are therefore the
authoritative historical record of what the engine observed; nothing in a
decision is ever re-derived from a live lookup.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from core.evidence_result.models import EvidenceResult
from core.policy.models import VerificationPolicy


class PolicyReference(BaseModel):
    """DE-003 §12, with `policy_hash` promoted alongside id/version per the
    DE-002 sign-off: identity alone does not pin *content*, and the named
    invariant `Decision.policy_reference == Session.policy_reference` is only
    meaningful bit-for-bit if the hash travels with it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    policy_version: int
    policy_hash: str

    @classmethod
    def from_policy(cls, policy: VerificationPolicy) -> "PolicyReference":
        """The only way the evaluator obtains a PolicyReference. The engine
        is never handed loose policy_id/version/hash values it could combine
        inconsistently -- it derives all three from the single pinned policy
        object it was given, so a decision cannot reference a policy it did
        not evaluate."""
        return cls(
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_hash=policy.canonical_hash,
        )


class EvidenceReference(BaseModel):
    """A soft reference: `evidence_result_id` identifies the historical
    evidence object that participated, and the remaining fields are the
    authoritative record of what it looked like at evaluation time.
    Deliberately carries no `result` payload -- a decision is not a place to
    duplicate biometric or document content (PRV-11.30.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_result_id: UUID
    evidence_type: str
    status: str
    integrity_reference: str

    @classmethod
    def from_evidence_result(cls, result: EvidenceResult) -> "EvidenceReference":
        return cls(
            evidence_result_id=result.id,
            evidence_type=result.evidence_type.value,
            status=result.status.value,
            integrity_reference=result.integrity_reference,
        )
