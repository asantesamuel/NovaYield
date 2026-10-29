"""Smoke checks for the NY-11 authentication dependency combination."""

import asyncio
import os
from inspect import signature
from uuid import uuid4

import pytest
from beanie import Document
from fastapi_users_db_beanie import BeanieBaseUserDocument, BeanieUserDatabase
from fastapi_users_db_beanie.access_token import (
    BeanieAccessTokenDatabase,
    BeanieBaseAccessTokenDocument,
)
from pwdlib import PasswordHash
from pydantic import SecretStr
from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.database.connection import MongoConnection


class AdapterProbeUser(BeanieBaseUserDocument):
    """Temporary document used to check the FastAPI Users Beanie adapter boundary."""

    class Settings(BeanieBaseUserDocument.Settings):
        name = "ny11_adapter_probe_users"


class AdapterProbeAccessToken(BeanieBaseAccessTokenDocument):
    """Temporary document used to check database-backed token adapter compatibility."""

    class Settings(BeanieBaseAccessTokenDocument.Settings):
        name = "ny11_adapter_probe_access_tokens"


def test_fastapi_users_adapters_accept_beanie_document_models() -> None:
    assert issubclass(AdapterProbeUser, Document)
    assert issubclass(AdapterProbeAccessToken, Document)

    user_database = BeanieUserDatabase(AdapterProbeUser)
    token_database = BeanieAccessTokenDatabase(AdapterProbeAccessToken)

    assert user_database.user_model is AdapterProbeUser
    assert token_database.access_token_model is AdapterProbeAccessToken


def test_pwdlib_argon2_extra_creates_verifiable_argon2id_hash() -> None:
    password_hash = PasswordHash.recommended()
    encoded_hash = password_hash.hash("ny11-compatibility-test-password")

    assert encoded_hash.startswith("$argon2id$")
    assert password_hash.verify("ny11-compatibility-test-password", encoded_hash)


def test_project_mongo_boundary_uses_pymongo_async_client() -> None:
    client_factory = signature(MongoConnection.__init__).parameters["client_factory"].default

    assert client_factory is AsyncMongoClient


def test_auth_adapters_persist_through_shared_beanie_connection_in_mongodb() -> None:
    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run the MongoDB adapter integration test")

    async def run() -> None:
        database_name = f"ny11_adapter_test_{uuid4().hex}"
        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(uri),
                mongodb_database_name=database_name,
            ),
            document_model_loader=lambda: (AdapterProbeUser, AdapterProbeAccessToken),
        )
        connected = False
        user = None
        token = None
        user_database = BeanieUserDatabase(AdapterProbeUser)
        token_database = BeanieAccessTokenDatabase(AdapterProbeAccessToken)

        try:
            connected = await connection.connect()
            assert connected

            user = await user_database.create(
                {
                    "email": f"adapter-probe-{uuid4().hex}@example.test",
                    "hashed_password": "not-a-real-password-hash",
                }
            )
            token = await token_database.create({"token": uuid4().hex, "user_id": user.id})

            stored_user = await user_database.get(user.id)
            stored_token = await token_database.get_by_token(token.token)

            assert stored_user is not None
            assert stored_user.id == user.id
            assert stored_token is not None
            assert stored_token.user_id == user.id
        finally:
            try:
                if connected:
                    if token is not None:
                        await token_database.delete(token)
                    if user is not None:
                        await user_database.delete(user)
                    await connection.client.drop_database(database_name)
            finally:
                await connection.close()

    asyncio.run(run())
