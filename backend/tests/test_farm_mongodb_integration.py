"""Optional Mongo checks for Farm v2 references, owner isolation and indexes."""

import asyncio
import os
from uuid import uuid4

import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from app.core.config import Settings
from app.database.connection import MongoConnection
from app.models.crop_catalog import Crop, CropCalendar, CropProfileRevision
from app.models.farm_reference_options import FarmReferenceOption
from app.models.farms import FARM_OWNER_INDEX_NAME, Farm
from app.models.supported_locations import SUPPORTED_LOCATION_KEY_INDEX_NAME, SupportedLocation
from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.farm_reference_options import FarmReferenceRepository
from app.repositories.farms import FarmRepository
from app.repositories.supported_locations import SupportedLocationRepository
from app.schemas.farms import FarmCreate, FarmUpdate


def test_farm_repository_persists_profiles_and_owner_index_in_mongodb() -> None:
    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run the farm MongoDB integration test")

    async def run() -> None:
        database_name = f"ny39_farm_test_{uuid4().hex}"
        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(uri),
                mongodb_database_name=database_name,
            ),
            document_model_loader=lambda: (
                Farm,
                SupportedLocation,
                Crop,
                CropProfileRevision,
                CropCalendar,
                FarmReferenceOption,
            ),
        )
        connected = False

        try:
            connected = await connection.connect()
            assert connected

            locations_inserted = await SupportedLocationRepository().seed_missing()
            assert locations_inserted == 3
            catalog_inserted = await CropCatalogRepository().seed_missing()
            assert catalog_inserted["crops"] == 8
            assert (await CropCatalogRepository().seed_missing()) == {
                "crops": 0,
                "profiles": 0,
                "calendars": 0,
            }
            assert await FarmReferenceRepository().seed_missing() == 8
            assert await FarmReferenceRepository().seed_missing() == 0
            repository = FarmRepository()
            owner_user_id = PydanticObjectId()
            other_user_id = PydanticObjectId()
            profile = FarmCreate.model_validate(
                {
                    "name": "Test field",
                    "location_key": "ejura",
                    "soil_texture_key": "loamy",
                    "irrigation_access_key": "none",
                    "history_status": "complete",
                    "crop_history": [
                        {
                            "crop_key": "maize",
                            "sequence_order": 1,
                            "start_date": "2024-03-15",
                            "end_date": "2024-07-15",
                        }
                    ],
                }
            )
            created = await repository.create(owner_user_id=owner_user_id, profile=profile)

            assert created.id is not None
            assert created.owner_user_id == owner_user_id
            assert created.schema_version == "farm-v2"
            assert created.crop_history[0].crop_key_snapshot == "maize"
            assert created.environmental_context.status == "pending"
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
