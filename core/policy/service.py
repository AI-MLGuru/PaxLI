import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from core.audit.enums import AuditActorType, AuditDurability, AuditEventType, AuditStatus
from core.audit.service import AuditService
from core.decision.enums import DecisionOutcome
from core.policy.canonicalization import compute_canonical_hash
from core.policy.condition import Condition
from core.policy.enums import PolicyStatus
from core.policy.exceptions import PolicyActivationConflictError, PolicyVersionNotFoundError
from core.policy.gates import Gate
from core.policy.models import VerificationPolicy
from core.policy.repository import VerificationPolicyRepository
from core.policy.requirements import EvidenceRequirement
from core.policy.rules import Rule
from core.policy.schema_catalog import EvidenceSchemaCatalog
from core.policy.thresholds import ThresholdDefinition
from core.policy.validation import validate_policy_content
from core.verification.enums import AssuranceLevel

logger = logging.getLogger(__name__)

ActivationType = Literal["INITIAL", "ROLLBACK"]

_SYSTEM_COMPONENT = "policy"


class IndependentAuditRecorder(Protocol):
    """Records one audit event in a transaction independent of the
    caller's own unit of work -- used only for failure-path audit, where
    the caller's own transaction is already aborted (a repository
    IntegrityError leaves a Postgres transaction unable to accept further
    statements) and cannot safely be reused (Invariant-12 remediation 2,
    Option 2). Kept as a narrow Protocol, not a concrete SQLAlchemy type,
    so core/ stays infrastructure-agnostic; the real implementation
    (infrastructure/audit/independent.py) owns its own session lifecycle,
    the same dependency-inversion shape as KeyProvider/RateLimiterProtocol
    elsewhere in this codebase."""

    async def record_independently(
        self,
        *,
        tenant_id: str,
        event_type: AuditEventType,
        component: str,
        action: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        request_id: str | None,
        correlation_id: str | None,
        metadata: dict[str, Any],
    ) -> None: ...


def _compose_idempotency_key(activation_type: ActivationType, idempotency_key: str) -> str:
    """Prefixes the caller-supplied key with the logical operation, so the
    same raw key reused across create-and-activate vs. rollback can never
    collide in the shared `(tenant_id, idempotency_key)` uniqueness scope
    (Invariant-12 remediation review -- idempotency must be operation-
    scoped, not merely tenant-scoped)."""
    operation = "policy_rollback" if activation_type == "ROLLBACK" else "policy_create_and_activate"
    return f"{operation}:{idempotency_key}"


class PolicyService:
    """Domain service for Part V §5.8-5.12 policy governance.

    Establishes "this is the authoritative, immutable policy that exists"
    only -- has no awareness of condition/gate/rule evaluation, and never
    produces a verification outcome (Foundation-009 constitutional
    boundary). The ordering below is the exact unit of work: validate,
    supersede the previous active version (if any), persist the new
    version, record the REQUIRED audit event, all inside the caller's
    existing transaction (get_db_session()) -- a required-audit failure
    rolls back the whole activation, never leaving an ambiguous active
    state (Invariant 12 / Foundation-009 discovery question 7).

    Note on statement order: superseding the previous active row happens
    BEFORE inserting the new ACTIVE row, not after. PostgreSQL partial
    unique indexes (the mechanism enforcing "at most one ACTIVE policy per
    tenant+assurance_level") are checked per-statement and cannot be made
    deferrable, so inserting a second ACTIVE row while the old one is still
    ACTIVE would violate the constraint immediately, even mid-transaction.
    The net guarantee -- nothing observable until the single final commit,
    audit-before-effect preserved -- is unchanged either way.
    """

    def __init__(
        self,
        repository: VerificationPolicyRepository,
        audit_service: AuditService,
        schema_catalog: EvidenceSchemaCatalog,
        failure_audit_recorder: IndependentAuditRecorder | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.schema_catalog = schema_catalog
        # Optional: no policy router exists yet (nothing currently calls
        # this service over HTTP), so there is no live call site that must
        # supply this today. Left unset, a PolicyActivationConflictError
        # still propagates untouched -- only the extra required failure
        # audit is skipped, logged as a warning so the gap is visible
        # rather than silent. Whichever future router wires this service
        # in MUST supply a real recorder (Invariant-12 remediation 2).
        self._failure_audit_recorder = failure_audit_recorder

    async def create_and_activate(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        assurance_level: AssuranceLevel,
        created_by: str,
        evidence_requirements: tuple[EvidenceRequirement, ...] = (),
        conditions: Condition | None = None,
        gates: tuple[Gate, ...] = (),
        rules: tuple[Rule, ...] = (),
        thresholds: tuple[ThresholdDefinition, ...] = (),
        default_outcome: DecisionOutcome | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> VerificationPolicy:
        """Raises InvalidPolicyError before anything is persisted (question 1:
        there is no draft state for an invalid policy). Raises
        PolicyActivationConflictError if a concurrent activation for the
        same (tenant_id, assurance_level) wins the race first.

        `idempotency_key`, if supplied, makes a retried request resolve to
        the same policy version rather than creating a second real
        activation -- Invariant-12 remediation: policy activation is a
        trust boundary, and an ambiguous-outcome retry must not silently
        produce two authoritative versions from one logical request."""
        return await self._activate(
            tenant_id=tenant_id,
            policy_id=policy_id,
            assurance_level=assurance_level,
            created_by=created_by,
            evidence_requirements=evidence_requirements,
            conditions=conditions,
            gates=gates,
            rules=rules,
            thresholds=thresholds,
            default_outcome=default_outcome,
            metadata=metadata or {},
            activation_type="INITIAL",
            rollback_source_id=None,
            idempotency_key=idempotency_key,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def rollback(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        target_version: int,
        created_by: str,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> VerificationPolicy:
        """Rollback NEVER reactivates the target row in place (Invariant 07
        §7.9, Foundation-009 discovery question 5): it reproduces the
        target version's content into a brand-new version and activates
        that. The target row remains exactly as it was, forever."""
        target = await self.repository.get_version(policy_id, target_version, tenant_id)
        if target is None:
            raise PolicyVersionNotFoundError(
                f"no version {target_version} of policy {policy_id!r} for this tenant"
            )
        return await self._activate(
            tenant_id=tenant_id,
            policy_id=policy_id,
            assurance_level=target.assurance_level,
            created_by=created_by,
            evidence_requirements=target.evidence_requirements,
            conditions=target.conditions,
            gates=target.gates,
            rules=target.rules,
            thresholds=target.thresholds,
            default_outcome=target.default_outcome,
            metadata=target.metadata,
            activation_type="ROLLBACK",
            rollback_source_id=target.id,
            idempotency_key=idempotency_key,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    async def _activate(
        self,
        *,
        tenant_id: str,
        policy_id: str,
        assurance_level: AssuranceLevel,
        created_by: str,
        evidence_requirements: tuple[EvidenceRequirement, ...],
        conditions: Condition | None,
        gates: tuple[Gate, ...],
        rules: tuple[Rule, ...],
        thresholds: tuple[ThresholdDefinition, ...],
        default_outcome: DecisionOutcome | None,
        metadata: dict[str, Any],
        activation_type: ActivationType,
        rollback_source_id: UUID | None,
        idempotency_key: str | None,
        request_id: str | None,
        correlation_id: str | None,
    ) -> VerificationPolicy:
        composed_idempotency_key = (
            _compose_idempotency_key(activation_type, idempotency_key)
            if idempotency_key is not None
            else None
        )
        if composed_idempotency_key is not None:
            existing = await self.repository.get_by_idempotency_key(
                tenant_id, composed_idempotency_key
            )
            if existing is not None:
                # Same-key replay of an already-completed activation: resolve
                # to the existing version rather than creating a second real
                # activation. Still records (dedupe-safe, via the resulting
                # policy's stable id) rather than silently skipping the audit
                # call, so the guarantee is uniform whether this is the first
                # attempt or a replay.
                await self.audit_service.record(
                    tenant_id=tenant_id,
                    event_type=AuditEventType.POLICY_ACTIVATED,
                    component=_SYSTEM_COMPONENT,
                    action="activate",
                    status=AuditStatus.SUCCESS,
                    actor_type=AuditActorType.CLIENT,
                    actor_id=created_by,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    metadata={
                        "policy_id": existing.policy_id,
                        "version": existing.version,
                        "assurance_level": existing.assurance_level.value,
                        "activation_type": activation_type,
                        "canonical_hash": existing.canonical_hash,
                        "idempotent_replay": True,
                    },
                    dedupe_key=f"policy-activated:{existing.id}",
                    durability=AuditDurability.REQUIRED,
                )
                return existing

        validate_policy_content(
            evidence_requirements=evidence_requirements,
            conditions=conditions,
            gates=gates,
            rules=rules,
            thresholds=thresholds,
            catalog=self.schema_catalog,
        )

        canonical_hash = compute_canonical_hash(
            schema_version=VerificationPolicy.model_fields["schema_version"].default,
            evidence_requirements=evidence_requirements,
            conditions=conditions,
            gates=gates,
            rules=rules,
            thresholds=thresholds,
            default_outcome=default_outcome,
        )

        now = datetime.now(UTC)
        previous_active = await self.repository.get_active(tenant_id, assurance_level)
        if previous_active is not None:
            await self.repository.mark_superseded(previous_active.id, tenant_id, now)

        next_version = await self.repository.get_max_version(policy_id, tenant_id) + 1
        new_policy = VerificationPolicy(
            id=uuid4(),
            policy_id=policy_id,
            version=next_version,
            tenant_id=tenant_id,
            assurance_level=assurance_level,
            status=PolicyStatus.ACTIVE,
            evidence_requirements=evidence_requirements,
            conditions=conditions,
            gates=gates,
            rules=rules,
            thresholds=thresholds,
            default_outcome=default_outcome,
            metadata=metadata,
            canonical_hash=canonical_hash,
            created_at=now,
            activated_at=now,
            supersedes_id=previous_active.id if previous_active is not None else None,
            created_by=created_by,
        )
        try:
            saved = await self.repository.add(new_policy, composed_idempotency_key)
        except PolicyActivationConflictError:
            if self._failure_audit_recorder is not None:
                try:
                    await self._failure_audit_recorder.record_independently(
                        tenant_id=tenant_id,
                        event_type=AuditEventType.POLICY_ACTIVATION_FAILED,
                        component=_SYSTEM_COMPONENT,
                        action="activate",
                        actor_type=AuditActorType.CLIENT,
                        actor_id=created_by,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        metadata={
                            "policy_id": policy_id,
                            "assurance_level": assurance_level.value,
                            "activation_type": activation_type,
                        },
                    )
                except Exception:
                    # The independent failure-audit write itself failed.
                    # Never mask the original conflict with a fabricated
                    # success/failure state -- log it and let the real
                    # PolicyActivationConflictError propagate unchanged
                    # (Invariant-12 remediation 2, explicit decision).
                    logger.error(
                        "policy_activation_failure_audit_failed",
                        extra={"tenant_id": tenant_id, "policy_id": policy_id},
                    )
            else:
                logger.warning(
                    "policy_activation_conflict_not_audited_no_recorder_configured",
                    extra={"tenant_id": tenant_id, "policy_id": policy_id},
                )
            raise

        await self.audit_service.record(
            tenant_id=tenant_id,
            event_type=AuditEventType.POLICY_ACTIVATED,
            component=_SYSTEM_COMPONENT,
            action="activate",
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.CLIENT,
            actor_id=created_by,
            request_id=request_id,
            correlation_id=correlation_id,
            metadata={
                "policy_id": policy_id,
                "version": next_version,
                "assurance_level": assurance_level.value,
                "activation_type": activation_type,
                "canonical_hash": canonical_hash,
                "previous_active_policy_id": (
                    str(previous_active.id) if previous_active is not None else None
                ),
                "previous_active_version": (
                    previous_active.version if previous_active is not None else None
                ),
                "rollback_source_policy_id": (
                    str(rollback_source_id) if rollback_source_id is not None else None
                ),
            },
            dedupe_key=f"policy-activated:{saved.id}",
            durability=AuditDurability.REQUIRED,
        )
        return saved

    async def get(self, *, policy_row_id: UUID, tenant_id: str) -> VerificationPolicy | None:
        return await self.repository.get(policy_row_id, tenant_id)

    async def get_active(
        self, *, tenant_id: str, assurance_level: AssuranceLevel
    ) -> VerificationPolicy | None:
        return await self.repository.get_active(tenant_id, assurance_level)

    async def get_version(
        self, *, policy_id: str, version: int, tenant_id: str
    ) -> VerificationPolicy | None:
        """Resolves a session's pinned (policy_id, policy_version) back to
        its full content -- the DE-002 §8 step 1 "context validation" read
        the evaluation orchestration boundary needs, now that early binding
        (DE-004 Phase 4) gives it a pin to resolve. Policies are never
        deleted (Invariant 07), only superseded, so this remains valid for
        the lifetime of any session that ever pinned it."""
        return await self.repository.get_version(policy_id, version, tenant_id)

    async def list_versions(
        self, *, policy_id: str, tenant_id: str
    ) -> Sequence[VerificationPolicy]:
        return await self.repository.list_versions(policy_id, tenant_id)
