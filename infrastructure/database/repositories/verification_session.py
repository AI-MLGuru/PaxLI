from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from core.verification.enums import VerificationStatus
from core.verification.exceptions import ConcurrentTransitionError
from core.verification.models import VerificationSession
from infrastructure.database.models.verification_session import (
    VerificationSessionRecord,
)


class SqlAlchemyVerificationSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, session: VerificationSession, idempotency_key: str | None = None
    ) -> VerificationSession:
        record = VerificationSessionRecord.from_domain(session, idempotency_key)
        self.session.add(record)
        await self.session.flush()
        return record.to_domain()

    async def get(self, session_id: UUID, tenant_id: str) -> VerificationSession | None:
        statement = select(VerificationSessionRecord).where(
            VerificationSessionRecord.id == str(session_id),
            VerificationSessionRecord.tenant_id == tenant_id,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def get_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> VerificationSession | None:
        statement = select(VerificationSessionRecord).where(
            VerificationSessionRecord.tenant_id == tenant_id,
            VerificationSessionRecord.idempotency_key == idempotency_key,
        )
        record = (await self.session.execute(statement)).scalar_one_or_none()
        return record.to_domain() if record else None

    async def list(self, tenant_id: str) -> Sequence[VerificationSession]:
        statement = select(VerificationSessionRecord).where(
            VerificationSessionRecord.tenant_id == tenant_id
        )
        records = (await self.session.execute(statement)).scalars().all()
        return [record.to_domain() for record in records]

    async def update(
        self, session: VerificationSession, *, expected_status: VerificationStatus
    ) -> VerificationSession:
        """WF-001 §11: a Core-level conditional UPDATE, not an ORM
        load-mutate-flush -- the WHERE clause's `status == expected_status`
        term is the compare-and-swap guard, checked by PostgreSQL itself,
        not by re-reading and comparing in application code first. Zero
        rows affected means either the session doesn't exist for this
        tenant, or (far more likely in practice) a concurrent transition
        already changed its status since the caller last read it; either
        way, this repository has no business guessing which -- it raises
        one exception and lets the caller (which knows what it was trying
        to do) decide how to react."""
        statement = (
            sql_update(VerificationSessionRecord)
            .where(
                VerificationSessionRecord.id == str(session.id),
                VerificationSessionRecord.tenant_id == session.tenant_id,
                VerificationSessionRecord.status == expected_status.value,
            )
            .values(
                status=session.status.value,
                expires_at=session.expires_at,
                completed_at=session.completed_at,
            )
        )
        result = cast("CursorResult[Any]", await self.session.execute(statement))
        if result.rowcount == 0:
            raise ConcurrentTransitionError(
                f"session_id={session.id!s} was not in status "
                f"{expected_status.value!r} for tenant={session.tenant_id!r} -- "
                "a concurrent transition already changed it, or it does not exist"
            )
        await self.session.flush()
        return session
