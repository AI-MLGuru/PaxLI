"""Integration tests against real PostgreSQL and MinIO (not fakes/mocks).

Skipped when either dependency isn't reachable in this environment, mirroring
tests/integration/test_migrations.py's pattern.
"""

import socket
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from apps.api.averiq_api.config import get_settings
from apps.api.averiq_api.main import app
from infrastructure.database.session import engine, session_factory
from infrastructure.reliability.dependency_health import DependencyHealthState
from infrastructure.reliability.postgres_policies import guarded_commit
from infrastructure.storage.minio import MinioObjectStorage

# The module-level `engine` singleton (one asyncpg pool for the process,
# matching real production usage) is loop-bound. pytest-asyncio's default
# function-scoped loop would open pooled connections under one test's loop
# and try to reuse/close them under a different test's loop, which asyncpg
# rejects with "Event loop is closed". A module-scoped loop matches how the
# engine is actually used in production: one process, one loop, one pool.
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest.fixture(scope="module", autouse=True)
async def _dispose_shared_engine_pool_after_module():
    """Disposes the shared engine's pooled connections while this module's
    loop is still open, so a later test (run under pytest-asyncio's default
    function-scoped loop) never inherits a connection bound to a loop that
    has since closed."""
    yield
    await engine.dispose()


def _postgres_reachable() -> bool:
    url = urlparse(get_settings().database_url.replace("+asyncpg", ""))
    try:
        with socket.create_connection((url.hostname, url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


def _minio_reachable() -> bool:
    settings = get_settings()
    host, _, port = settings.storage_endpoint.partition(":")
    try:
        with socket.create_connection((host, int(port) if port else 9000), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _postgres_reachable(), reason="PostgreSQL is not reachable")
async def test_guarded_commit_against_real_postgres_succeeds() -> None:
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))
        await guarded_commit(session)  # must not raise


@pytest.mark.skipif(not _minio_reachable(), reason="MinIO is not reachable")
async def test_guarded_put_get_delete_against_real_minio_round_trips() -> None:
    settings = get_settings()
    storage = MinioObjectStorage(settings)
    key = "test/reliability/roundtrip-object"
    content = b"CANARY_INTEGRATION_ROUNDTRIP_BYTES"

    await storage.put(key, content, "application/octet-stream")
    fetched = await storage.get(key)
    assert fetched == content

    await storage.delete(key)
    await storage.delete(key)  # idempotent: deleting an already-deleted key is a no-op


@pytest.mark.skipif(
    not (_postgres_reachable() and _minio_reachable()),
    reason="PostgreSQL and/or MinIO not reachable",
)
async def test_ready_reports_healthy_against_real_infrastructure() -> None:
    import httpx

    # An async client sharing this test's own event loop, rather than the
    # sync TestClient's separate portal -- the module-level async engine's
    # pooled connections are loop-bound, and reusing them from a different
    # loop than the one that opened them raises "Event loop is closed".
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["postgres"] == DependencyHealthState.HEALTHY.value
    assert body["dependencies"]["storage"] == DependencyHealthState.HEALTHY.value
