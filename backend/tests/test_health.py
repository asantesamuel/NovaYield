"""Smoke tests for application startup and health/readiness contracts."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


class FakeMongoConnection:
    def __init__(self, ready: bool = False, error: Exception | None = None) -> None:
        self.ready = ready
        self.error = error
        self.closed = False

    async def connect(self) -> bool:
        return self.ready

    async def is_ready(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.ready

    async def close(self) -> None:
        self.closed = True


def make_app(*, database_ready: bool = False) -> tuple[TestClient, FakeMongoConnection]:
    settings = Settings(
        _env_file=None,
        app_name="Nova Yield Test API",
        cors_allowed_origins="http://localhost:5173",
    )
    mongo = FakeMongoConnection(database_ready)
    app = create_app(settings, mongo_connection_factory=lambda _settings: mongo)
    return TestClient(app), mongo


def test_application_starts_and_exposes_openapi() -> None:
    client, _mongo = make_app()
    with client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Nova Yield Test API"


def test_liveness_does_not_depend_on_database_readiness() -> None:
    client, _mongo = make_app()
    with client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_unavailable_database() -> None:
    client, _mongo = make_app()
    with client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }


def test_readiness_reflects_registered_database_check() -> None:
    settings = Settings(_env_file=None)
    mongo = FakeMongoConnection(ready=True)
    app = create_app(settings, mongo_connection_factory=lambda _settings: mongo)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
    assert mongo.closed


def test_readiness_does_not_return_dependency_exception_text() -> None:
    settings = Settings(_env_file=None)
    mongo = FakeMongoConnection(
        ready=False,
        error=RuntimeError("mongodb://private-user:private-password@database"),
    )
    app = create_app(settings, mongo_connection_factory=lambda _settings: mongo)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert "private-password" not in response.text
    assert "mongodb://" not in response.text


def test_cors_allows_configured_frontend_origin_with_credentials() -> None:
    client, _mongo = make_app()
    with client:
        response = client.options(
            "/api/v1/example",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_wildcard_origin() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS origins are not allowed"):
        Settings(_env_file=None, cors_allowed_origins="*")
