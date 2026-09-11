from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from apps.api.averiq_api.config import Settings, get_settings
from apps.api.averiq_api.dependencies import get_evidence_service, get_rate_limiter
from apps.api.averiq_api.main import app
from core.audit.service import AuditService
from core.evidence.service import EvidenceService
from core.rate_limit.models import RateLimitDecision, RateLimitRule
from core.security.credentials import CredentialService
from core.security.models import CredentialScope
from core.verification.service import VerificationSessionService
from infrastructure.database.base import Base
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.credential import SqlAlchemyCredentialStore
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import get_db_session
from infrastructure.security.hashing import ScryptSecretHasher
from infrastructure.security.local_key_provider import LocalAesGcmKeyProvider
from infrastructure.storage.encrypted import EncryptedObjectStorage

# A minimal, structurally valid JPEG (real signature bytes) so evidence-upload
# tests pass server-side media validation (SEC-7.22.2) while still letting
# tests append distinguishing/canary payload after the signature.
MINIMAL_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


class FakeObjectStorage:
    """In-memory `ObjectStorage` so tests never require a live MinIO server."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, bytes, str]] = []

    async def put(self, object_key: str, content: bytes, content_type: str) -> None:
        self.blobs[object_key] = content
        self.put_calls.append((object_key, content, content_type))

    async def get(self, object_key: str) -> bytes:
        return self.blobs[object_key]

    async def delete(self, object_key: str) -> None:
        self.blobs.pop(object_key, None)


class AlwaysAllowRateLimiter:
    """Default `api_client` override: unrelated tests share the TestClient's
    single fake IP/credential set, so a real limiter would let the request
    count accumulate across the whole test suite and eventually reject
    tests that have nothing to do with Foundation-010. Tests that actually
    exercise rate-limiting behavior override get_rate_limiter again
    themselves, within the test, with a more controlled fake."""

    async def check_and_consume(self, scope_key: str, rule: RateLimitRule) -> RateLimitDecision:
        return RateLimitDecision(allowed=True, remaining=rule.limit, retry_after_seconds=0)


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
def raw_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def api_client(session_factory, raw_storage):
    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    key_provider = LocalAesGcmKeyProvider({"test-evidence-key": b"0" * 32})

    async def override_get_evidence_service(
        db_session: AsyncSession = Depends(override_get_db_session),  # noqa: B008
        settings: Settings = Depends(get_settings),  # noqa: B008
    ) -> AsyncIterator[EvidenceService]:
        session_repository = SqlAlchemyVerificationSessionRepository(db_session)
        storage = EncryptedObjectStorage(raw_storage, key_provider, "test-evidence-key")
        yield EvidenceService(
            SqlAlchemyEvidenceRepository(db_session),
            VerificationSessionService(
                session_repository, session_ttl_minutes=settings.session_ttl_minutes
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(db_session)),
        )

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_evidence_service] = override_get_evidence_service
    app.dependency_overrides[get_rate_limiter] = lambda: AlwaysAllowRateLimiter()
    original_db_session_factory = app.state.db_session_factory
    app.state.db_session_factory = session_factory
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.state.db_session_factory = original_db_session_factory


@pytest_asyncio.fixture
async def issued_credentials(session_factory) -> dict[str, str]:
    """Bearer tokens for two tenants, each with an operational and an administrative credential."""
    async with session_factory() as session:
        service = CredentialService(SqlAlchemyCredentialStore(session), ScryptSecretHasher())
        tokens: dict[str, str] = {}
        for label, tenant_id, scope in (
            ("tenant_a_operational", "tenant-a", CredentialScope.OPERATIONAL),
            ("tenant_a_admin", "tenant-a", CredentialScope.ADMINISTRATIVE),
            ("tenant_b_operational", "tenant-b", CredentialScope.OPERATIONAL),
        ):
            issued = await service.issue(
                tenant_id=tenant_id, name=label, scope=scope, expires_in=timedelta(days=1)
            )
            tokens[label] = f"Bearer {issued.credential_id}.{issued.secret}"
        await session.commit()
        return tokens
