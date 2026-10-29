"""Opt-in MongoDB integration check for NY-6 snapshot persistence and reuse."""

import asyncio
import os
from datetime import UTC, date, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.database.connection import MongoConnection
from app.integrations.nasa.power import NASAPowerService, PowerRequest
from app.models.environmental_snapshots import (
    REQUEST_KEY_INDEX_NAME,
    SNAPSHOT_COLLECTION_NAME,
    EnvironmentalSnapshot,
)
from app.services.environmental_snapshots import EnvironmentalSnapshotService

TEST_REQUEST = PowerRequest(
    latitude=0.0,
    longitude=0.0,
    start_date=date(2024, 1, 1),
    end_date=date(2024, 1, 2),
    season_label="integration-test-window",
    calendar_source_version="integration-test-v1",
    crop="integration-test-crop",
)
TEST_LOCATION_SECRET = "ny6-integration-test-location-key-at-least-32-bytes"


def make_power_payload(request: PowerRequest) -> dict[str, Any]:
    """Return a small NASA-shaped response for the real normalizer to process."""

    dates = []
    current = request.start_date
    while current <= request.end_date:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [request.longitude, request.latitude]},
        "properties": {
            "parameter": {
                "PRECTOTCORR": {day: 2.0 for day in dates},
                "T2M": {day: 28.0 for day in dates},
                "T2M_MAX": {day: 34.0 for day in dates},
            }
        },
        "header": {
            "title": "NASA POWER Daily Source Native Resolution",
            "api": {"name": "POWER Daily API", "version": "v2"},
            "fill_value": -999,
            "sources": ["MERRA2"],
        },
        "messages": [],
        "parameters": {
            "PRECTOTCORR": {
                "units": "mm/day",
                "longname": "Precipitation",
                "source": "MERRA2",
            },
            "T2M": {"units": "C", "longname": "Temperature", "source": "MERRA2"},
            "T2M_MAX": {
                "units": "C",
                "longname": "Maximum temperature",
                "source": "MERRA2",
            },
        },
        "times": {},
    }


class MockPowerClient:
    """Replace only the external provider transport; keep NY-5 normalization real."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_daily_point(self, request: PowerRequest) -> dict[str, Any]:
        self.calls += 1
        return make_power_payload(request)


def test_snapshot_is_persisted_in_mongodb_and_reused_without_provider_call() -> None:
    mongodb_uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not mongodb_uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run the MongoDB integration test")

    async def run() -> None:
        database_name = f"ny6_test_{uuid4().hex}"
        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(mongodb_uri),
                mongodb_database_name=database_name,
            )
        )
        connected = False
        try:
            connected = await connection.connect()
            assert connected

            provider = MockPowerClient()
            service = EnvironmentalSnapshotService(
                nasa_service=NASAPowerService(provider),
                location_secret=TEST_LOCATION_SECRET,
            )
            first = await service.retrieve(TEST_REQUEST)
            second = await service.retrieve(TEST_REQUEST)

            assert first.snapshot is not None
            assert second.snapshot is not None
            assert first.data_status == "live"
            assert second.data_status == "cached"
            assert first.snapshot.id == second.snapshot.id
            assert second.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 4.0
            assert provider.calls == 1

            documents = connection.database[SNAPSHOT_COLLECTION_NAME]
            assert await documents.count_documents({}) == 1
            indexes = await documents.list_indexes().to_list(length=None)
            request_key_index = next(
                index for index in indexes if index["name"] == REQUEST_KEY_INDEX_NAME
            )
            assert request_key_index["unique"] is True

            stored = await EnvironmentalSnapshot.find_one(
                {"identity.request_key": first.snapshot.identity.request_key},
                ignore_cache=True,
            )
            assert stored is not None
            stored_retrieved_at = stored.retrieved_at.replace(tzinfo=UTC)
            assert abs((stored_retrieved_at - first.snapshot.retrieved_at).total_seconds()) < 0.001
        finally:
            try:
                if connected:
                    await connection.client.drop_database(database_name)
            finally:
                await connection.close()

    asyncio.run(run())
