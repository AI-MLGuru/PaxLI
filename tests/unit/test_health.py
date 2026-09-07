from fastapi.testclient import TestClient

from apps.api.averiq_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness() -> None:
    response = client.get("/ready")
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert response.json()["status"] == "ready"
    else:
        assert response.json()["error"]["code"] == "REQUEST_ERROR"
