from fastapi.testclient import TestClient

from autonomous_engineering.core.config import Settings
from autonomous_engineering.main import create_app


def test_health_returns_ok(monkeypatch) -> None:
    monkeypatch.setenv("ASE_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    app = create_app(settings)

    # The context manager exercises application startup and shutdown too.
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
