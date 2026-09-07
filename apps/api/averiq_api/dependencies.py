from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.averiq_api.config import Settings, get_settings
from core.verification.service import VerificationSessionService
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import get_db_session


async def get_session_service(
    db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[VerificationSessionService]:
    yield VerificationSessionService(
        SqlAlchemyVerificationSessionRepository(db_session),
        session_ttl_minutes=settings.session_ttl_minutes,
    )
