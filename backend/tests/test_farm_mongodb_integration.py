"""Optional integration checks for the NY-19 document and owner index."""

import asyncio
import os
from uuid import uuid4

import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from app.core.config import Settings
from app.database.connection import MongoConnection
from app.models.farms import FARM_OWNER_INDEX_NAME, Farm
from app.models.supported_locations import SUPPORTED_LOCATION_KEY_INDEX_NAME, SupportedLocation
from app.repositories.farms import FarmRepository
from app.repositories.supported_locations import SupportedLocationRepository
from app.schemas.farms import FarmCreate, FarmUpdate


def test_farm_repository_persists_profiles_and_owner_index_in_mongodb() -> None:
    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run the farm MongoDB integration test")

    async def run() -> None:
        database_name = f"ny19_farm_test_{uuid4().hex}"
        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(uri),
                mongodb_database_name=database_name,
            ),
            document_model_loader=lambda: (Farm, SupportedLocation),
        )
        connected = False

        try:
            connected = await connection.connect()
            assert connected

            locations_inserted = await SupportedLocationRepository().seed_missing()
            assert locations_inserted == 3
            repository = FarmRepository()
            owner_user_id = PydanticObjectId()
            other_user_id = PydanticObjectId()
            profile = FarmCreate.model_validate(
                {
                    "name": "Test field",
                    "location_key": "ejura",
                    "soil_texture": "sandy loam",
                }
            )
            created = await repository.create(owner_user_id=owner_user_id, profile=profile)

            assert created.id is not None
            assert created.owner_user_id == owner_user_id
            assert [
                farm.id for farm in await repository.list_by_owner(owner_user_id=owner_user_id)
            ] == [created.id]
            assert (
                await repository.get_by_owner(
                    farm_id=created.id,
                    owner_user_id=other_user_id,
                )
                is None
            )
            assert (
                await repository.update_by_owner(
                    farm_id=created.id,
                    owner_user_id=other_user_id,
                    changes=FarmUpdate.model_validate({"name": "Unauthorized update"}),
                )
                is None
            )

            unchanged = await repository.get_by_owner(
                farm_id=created.id,
                owner_user_id=owner_user_id,
            )
            assert unchanged is not None
            assert unchanged.name == "Test field"

            updated = await repository.update_by_owner(
                farm_id=created.id,
                owner_user_id=owner_user_id,
                changes=FarmUpdate.model_validate({"name": "South field"}),
            )
            assert updated is not None
            assert updated.name == "South field"

            indexes = await Farm.get_pymongo_collection().index_information()
            assert FARM_OWNER_INDEX_NAME in indexes
            assert indexes[FARM_OWNER_INDEX_NAME]["key"] == [("owner_user_id", 1)]
            location_indexes = await SupportedLocation.get_pymongo_collection().index_information()
            assert SUPPORTED_LOCATION_KEY_INDEX_NAME in location_indexes
            assert location_indexes[SUPPORTED_LOCATION_KEY_INDEX_NAME]["unique"] is True
        finally:
            try:
                if connected:
                    await connection.client.drop_database(database_name)
            finally:
                await connection.close()

    asyncio.run(run())
