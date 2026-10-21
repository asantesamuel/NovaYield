"""Focused tests for the shared MongoDB connection and Beanie initialization boundary."""

import asyncio
import logging
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from beanie import Document
from pydantic import SecretStr
from pymongo import ASCENDING, IndexModel
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import Settings
from app.database import registry
from app.database.connection import MongoConnection


class RegistryProbe(Document):
    request_key: str

    class Settings:
        name = "ny4_registry_probe"
        indexes = [
            IndexModel(
                [("request_key", ASCENDING)],
                unique=True,
                name="uq_ny4_registry_probe_request_key",
            )
        ]


class FakeAdmin:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.commands: list[str] = []

    async def command(self, name: str) -> dict[str, int]:
        self.commands.append(name)
        if self.error is not None:
            raise self.error
        return {"ok": 1}


class FakeDatabase:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeClient:
    def __init__(self) -> None:
        self.admin = FakeAdmin()
        self.databases: dict[str, FakeDatabase] = {}
        self.closed = False
        self.drop_database_names: list[str] = []

    def __getitem__(self, name: str) -> FakeDatabase:
        return self.databases.setdefault(name, FakeDatabase(name))

    async def close(self) -> None:
        self.closed = True


def test_feature_document_can_register_without_a_bootstrap_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "_registered_document_models", {})
    models_package = SimpleNamespace(__name__="app.models", __path__=())
    imported_modules: list[str] = []

    def fake_import_module(module_name: str) -> object:
        imported_modules.append(module_name)
        if module_name == "app.models":
            return models_package
        registry.register_document_model(RegistryProbe)
        return object()

    monkeypatch.setattr(registry, "import_module", fake_import_module)
    monkeypatch.setattr(
        registry,
        "iter_modules",
        lambda _package_path: [SimpleNamespace(name="farms")],
    )

    assert registry.load_document_models() == (RegistryProbe,)
    assert imported_modules == ["app.models", "app.models.farms"]


def test_connection_initializes_beanie_once_and_closes_shared_client() -> None:
    async def run() -> None:
        settings = Settings(_env_file=None, mongodb_database_name="ny4_tests")
        client = FakeClient()
        factory_calls: list[tuple[str, dict[str, int]]] = []
        initializer_calls: list[dict[str, object]] = []

        def make_client(uri: str, **options: int) -> FakeClient:
            factory_calls.append((uri, options))
            return client

        async def initialize_beanie(**kwargs: object) -> None:
            initializer_calls.append(kwargs)

        connection = MongoConnection(
            settings,
            client_factory=make_client,
            beanie_initializer=initialize_beanie,
            document_model_loader=lambda: (RegistryProbe,),
        )

        assert await connection.connect()
        assert await connection.connect()
        assert await connection.is_ready()
        assert connection.database is client["ny4_tests"]
        assert connection.client is client
        assert factory_calls == [
            (
                "mongodb://localhost:27017",
                {"serverSelectionTimeoutMS": 2_000},
            )
        ]
        assert len(initializer_calls) == 1
        assert initializer_calls[0]["database"] is connection.database
        assert initializer_calls[0]["document_models"] == (RegistryProbe,)
        assert RegistryProbe.Settings.indexes[0].document["unique"] is True
        assert client.admin.commands == ["ping", "ping", "ping"]

        await connection.close()
        assert client.closed

    asyncio.run(run())


def test_unavailable_database_does_not_initialize_or_log_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        secret_uri = "mongodb://private-user:private-password@db.example.test:27017"
        client = FakeClient()
        client.admin.error = ServerSelectionTimeoutError(secret_uri)
        initializer_calls: list[dict[str, object]] = []

        async def initialize_beanie(**kwargs: object) -> None:
            initializer_calls.append(kwargs)

        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(secret_uri),
            ),
            client_factory=lambda *_args, **_kwargs: client,
            beanie_initializer=initialize_beanie,
            document_model_loader=lambda: (RegistryProbe,),
        )

        caplog.set_level(logging.WARNING)
        assert not await connection.connect()
        assert not await connection.is_ready()
        assert initializer_calls == []
        assert secret_uri not in caplog.text
        assert "private-password" not in repr(
            Settings(_env_file=None, mongodb_uri=SecretStr(secret_uri))
        )
        assert "private-password" not in caplog.text

        await connection.close()

    asyncio.run(run())


def test_beanie_initialization_failure_keeps_database_unready() -> None:
    async def run() -> None:
        client = FakeClient()
        secret_detail = "mongodb://private-user:private-password@index-failure"

        async def initialize_beanie(**_kwargs: object) -> None:
            raise ServerSelectionTimeoutError(secret_detail)

        connection = MongoConnection(
            Settings(_env_file=None),
            client_factory=lambda *_args, **_kwargs: client,
            beanie_initializer=initialize_beanie,
            document_model_loader=lambda: (RegistryProbe,),
        )

        assert not await connection.connect()
        assert not await connection.is_ready()
        await connection.close()

    asyncio.run(run())


def test_mongodb_database_name_validation() -> None:
    with pytest.raises(ValueError, match="unsupported character"):
        Settings(_env_file=None, mongodb_database_name="bad database")


def test_mongodb_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVAYIELD_MONGODB_URI", "mongodb://dev-user:dev-password@localhost:27017")
    monkeypatch.setenv("NOVAYIELD_MONGODB_DATABASE_NAME", "nova_yield_test")
    monkeypatch.setenv("NOVAYIELD_MONGODB_SERVER_SELECTION_TIMEOUT_MS", "750")

    settings = Settings(_env_file=None)

    assert settings.mongodb_uri.get_secret_value() == (
        "mongodb://dev-user:dev-password@localhost:27017"
    )
    assert settings.mongodb_database_name == "nova_yield_test"
    assert settings.mongodb_server_selection_timeout_ms == 750


def test_beanie_creates_declared_index_in_mongodb_integration() -> None:
    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run the MongoDB integration test")

    async def run() -> None:
        database_name = f"ny4_test_{uuid4().hex}"
        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(uri),
                mongodb_database_name=database_name,
            ),
            document_model_loader=lambda: (RegistryProbe,),
        )
        connected = False
        try:
            connected = await connection.connect()
            assert connected
            indexes = (
                await connection.database["ny4_registry_probe"].list_indexes().to_list(length=None)
            )
            matching_index = next(
                index for index in indexes if index["name"] == "uq_ny4_registry_probe_request_key"
            )
            assert matching_index["unique"] is True
            assert matching_index["key"] == {"request_key": ASCENDING}
        finally:
            try:
                if connected:
                    await connection.client.drop_database(database_name)
            finally:
                await connection.close()

    asyncio.run(run())
