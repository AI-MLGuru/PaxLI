import os
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.paxli_api.config import Settings, get_settings
from apps.api.paxli_api.dependencies import (
    get_evidence_result_service,
    get_evidence_service,
    get_object_storage,
    get_rate_limiter,
    get_session_factory,
)
from apps.api.paxli_api.main import app
from core.audit.service import AuditService
from core.evidence.service import EvidenceService
from core.evidence_result.service import EvidenceResultService
from core.rate_limit.models import RateLimitDecision, RateLimitRule
from core.security.credentials import CredentialService
from core.security.models import CredentialScope
from core.verification.service import VerificationSessionService
from infrastructure.database.base import Base
from infrastructure.database.models.policy import PolicyRecord
from infrastructure.database.repositories.audit_event import SqlAlchemyAuditEventRepository
from infrastructure.database.repositories.credential import SqlAlchemyCredentialStore
from infrastructure.database.repositories.evidence import SqlAlchemyEvidenceRepository
from infrastructure.database.repositories.evidence_result import (
    SqlAlchemyEvidenceResultRepository,
)
from infrastructure.database.repositories.verification_session import (
    SqlAlchemyVerificationSessionRepository,
)
from infrastructure.database.session import get_db_session
from infrastructure.deletion.reconciliation import (
    SqlAlchemyEvidenceDeletionReconciler,
    SqlAlchemyEvidenceResultDeletionReconciler,
)
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
    """A per-test temp-file SQLite database, not a private `:memory:` one
    -- required since DocumentProcessor (DP-001 Decision 4) opens its own
    independent session(s) beyond whatever ambient request-scoped session
    an api_client call already holds open for the whole request. A
    single-connection StaticPool (this fixture's original approach)
    cannot serve both the ambient session and DocumentProcessor's own at
    once -- confirmed live as a genuine deadlock, not assumed.

    A shared-cache in-memory database (`file::memory:?cache=shared`) was
    tried first and rejected: it allows multiple simultaneous connections
    in principle, but produced a genuine Windows access violation inside
    SQLAlchemy's ORM session internals under real concurrent access from
    this project's async stack -- a serious, not merely inconvenient,
    failure mode, confirmed via a minimal reproduction outside pytest
    before being ruled out. A real temp file, letting SQLite's normal
    file-level concurrency control do its job, does not exhibit this;
    confirmed via the same kind of minimal reproduction before adopting
    it here."""
    path = os.path.join(tempfile.gettempdir(), f"pytest_{uuid4().hex}.sqlite3")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    # A real file's normal single-writer locking, discovered immediately
    # after switching away from in-memory SQLite: concurrent sessions
    # (the ambient request session plus DocumentProcessor's own) now hit
    # genuine "database is locked" errors under SQLite's default
    # rollback-journal mode. WAL mode allows one writer alongside
    # concurrent readers without that contention; busy_timeout makes any
    # remaining brief lock wait retry for up to 5s instead of failing
    # immediately. Registered on the sync engine's "connect" event so
    # every pooled connection gets both pragmas, not just the first.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
def raw_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


async def _activate_standard_policy(session_factory, tenant_id: str) -> None:
    """DE-002/DE-003 §1 early policy binding made VerificationSessionService.
    create() depend on an ACTIVE policy existing for (tenant_id,
    assurance_level) -- every contract/integration test that creates a
    session via api_client now needs one to already exist, the same way
    `issued_credentials` pre-seeds authentication. A raw PolicyRecord
    insert, not PolicyService.create_and_activate(): this is fixture setup,
    not something under test, and every api_client test uses STANDARD
    (the schema default -- apps/api/paxli_api/schemas/verification.py)."""
    async with session_factory() as session:
        session.add(
            PolicyRecord(
                id=str(uuid4()),
                policy_id=f"test-fixture-default-{tenant_id}",
                version=1,
                tenant_id=tenant_id,
                assurance_level="STANDARD",
                schema_version="1.0",
                status="ACTIVE",
                evidence_requirements_json=[],
                gates_json=[],
                rules_json=[],
                thresholds_json=[],
                metadata_json={},
                canonical_hash=f"test-fixture-hash-{tenant_id}",
                created_at=datetime.now(UTC),
                activated_at=datetime.now(UTC),
                created_by="test-fixture",
            )
        )
        await session.commit()


@pytest_asyncio.fixture
async def api_client(session_factory, raw_storage):
    # Awaited directly, inside pytest-asyncio's own managed event loop --
    # NOT asyncio.run(), which spins up and tears down a separate loop and
    # corrupts the "current event loop" state asyncio.get_event_loop()
    # depends on for whichever async test runs next (confirmed by running
    # the full suite with asyncio.run() here: four unrelated async tests
    # failed with "There is no current event loop in thread 'MainThread'").
    for tenant_id in ("tenant-a", "tenant-b"):
        await _activate_standard_policy(session_factory, tenant_id)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    key_provider = LocalAesGcmKeyProvider({"test-evidence-key": b"0" * 32})

    # Depends(get_db_session) here, NOT Depends(override_get_db_session):
    # FastAPI's dependency cache key is the declared `call` as WRITTEN in
    # each Depends() marker, resolved to its override (if any) only at
    # invocation time -- it does not unify two different declared
    # dependencies just because they both happen to override to the same
    # function. get_audit_service/get_credential_service elsewhere declare
    # Depends(get_db_session); declaring Depends(override_get_db_session)
    # here instead made FastAPI treat this as a SEPARATE, uncached
    # dependency, so every request opened a second independent session/
    # connection alongside the real ambient one. Under the old
    # single-connection StaticPool SQLite setup the two sessions silently
    # shared the same underlying DBAPI connection and this went unnoticed;
    # switching to a real multi-connection temp-file database turned it
    # into a genuine two-writer SQLite lock (confirmed live via connection-
    # identity tracing, not assumed).
    async def override_get_evidence_service(
        db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
        settings: Settings = Depends(get_settings),  # noqa: B008
    ) -> AsyncIterator[EvidenceService]:
        session_repository = SqlAlchemyVerificationSessionRepository(db_session)
        storage = EncryptedObjectStorage(raw_storage, key_provider, "test-evidence-key")
        yield EvidenceService(
            SqlAlchemyEvidenceRepository(db_session),
            VerificationSessionService(
                session_repository,
                audit_service=AuditService(SqlAlchemyAuditEventRepository(db_session)),
                session_ttl_minutes=settings.session_ttl_minutes,
            ),
            storage,
            AuditService(SqlAlchemyAuditEventRepository(db_session)),
            deletion_reconciler=SqlAlchemyEvidenceDeletionReconciler(session_factory, storage),
        )

    async def override_get_evidence_result_service(
        db_session: AsyncSession = Depends(get_db_session),  # noqa: B008
    ) -> AsyncIterator[EvidenceResultService]:
        yield EvidenceResultService(
            SqlAlchemyEvidenceResultRepository(db_session, key_provider, "test-evidence-key"),
            AuditService(SqlAlchemyAuditEventRepository(db_session)),
            SqlAlchemyEvidenceRepository(db_session),
            deletion_reconciler=SqlAlchemyEvidenceResultDeletionReconciler(
                session_factory, key_provider, "test-evidence-key"
            ),
        )

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_evidence_service] = override_get_evidence_service
    app.dependency_overrides[get_evidence_result_service] = override_get_evidence_result_service
    app.dependency_overrides[get_rate_limiter] = lambda: AlwaysAllowRateLimiter()
    # DocumentProcessor (via get_workflow_service) opens its OWN independent
    # sessions/storage beyond the single ambient db_session (DP-001 Decision
    # 4) -- get_db_session's override alone doesn't reach those, since they
    # aren't sub-dependencies of it. Without these two, DocumentProcessor
    # would silently talk to the real Postgres/MinIO backends on every
    # /submit call in every SQLite-backed test.
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_object_storage] = lambda: EncryptedObjectStorage(
        raw_storage, key_provider, "test-evidence-key"
    )
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
            ("tenant_b_admin", "tenant-b", CredentialScope.ADMINISTRATIVE),
        ):
            issued = await service.issue(
                tenant_id=tenant_id, name=label, scope=scope, expires_in=timedelta(days=1)
            )
            tokens[label] = f"Bearer {issued.credential_id}.{issued.secret}"
        await session.commit()
        return tokens
