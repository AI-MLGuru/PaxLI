from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.averiq_api.config import Settings, get_settings
from core.audit.service import AuditService
from core.evidence.service import EvidenceService
from core.verification.service import VerificationSessionService
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import get_db_session
from infrastructure.storage.minio import MinioObjectStorage


async def get_session_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[VerificationSessionService]:
    yield VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(db_session),
        session_ttl_minutes=settings.session_ttl_minutes,
    )


async def get_evidence_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[EvidenceService]:
    session_repository = SqlAlchemyVerificationSessionRepository(db_session)
    yield EvidenceService(
        SqlAlchemyEvidenceRepository(db_session),
        VerificationSessionService(
            session_repository,
            session_ttl_minutes=settings.session_ttl_minutes,
        ),
        MinioObjectStorage(settings),
    )


async def get_audit_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AsyncIterator[AuditService]:
    yield AuditService(SqlAlchemyAuditEventRepository(db_session))
