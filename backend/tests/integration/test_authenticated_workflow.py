"""Opt-in real-Mongo checks for the authenticated NY-39/NY-40 API workflow.

Only a uniquely named local test database is touched. NASA's HTTP transport is
synthetic, so these tests are repeatable and never send coordinates upstream.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi import FastAPI
from pydantic import SecretStr
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.database.connection import MongoConnection
from app.farms.routes import get_farm_repository
from app.integrations.nasa.power import NASA_POWER_DAILY_ENDPOINT
from app.main import create_app
from app.models.access_tokens import AccessToken
from app.models.crop_catalog import (
    Crop,
    CropCalendar,
    CropProfileRevision,
    EvidenceValue,
    GrowthStage,
    MaturityEvidence,
    MaturityRange,
    PlantingWindow,
    SourceEvidence,
)
from app.models.environmental_snapshots import EnvironmentalSnapshot
from app.models.rotation_results import ROTATION_RESULTS_COLLECTION_NAME
from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.farm_reference_options import FarmReferenceRepository
from app.repositories.supported_locations import SupportedLocationRepository
from app.services.authentication import AUTH_COOKIE_NAME, AUTH_CSRF_COOKIE_NAME

from .demo_profile import (
    CONTEXT_END,
    CONTEXT_POWER_WINDOW,
    CONTEXT_START,
    DECLARED_GAPS,
    FARM_REQUEST,
    HISTORY_EVENTS,
    PROFILE_ID,
    PROFILE_STATUS,
    SYNTHETIC_PASSWORD,
    recommendation_request,
)

FRONTEND_ORIGIN = "http://localhost:5173"
CSRF_TEST_SECRET = "ny10-synthetic-csrf-key-long-enough-for-tests-only"
LOCATION_TEST_SECRET = "ny10-synthetic-location-key-long-enough-for-tests-only"
MONGO_FAILURE_MARKER = "synthetic-private-mongo-diagnostic"
UPSTREAM_FAILURE_MARKER = "synthetic-private-provider-diagnostic"
PRIVATE_EJURA_COORDINATES = ("7.3856", "-1.3562")


class SyntheticNASAPower:
    """Return deterministic POWER-shaped daily data without network access."""

    def __init__(self, mode: Literal["complete", "partial", "unavailable"] = "complete") -> None:
        self.mode = mode
        # Store only dates; raw coordinates are never logged or retained here.
        self.request_windows: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        endpoint = httpx.URL(NASA_POWER_DAILY_ENDPOINT)
        if (
            request.url.scheme != endpoint.scheme
            or request.url.host != endpoint.host
            or request.url.path != endpoint.path
        ):
            return httpx.Response(404, json={"error": "Unexpected synthetic URL"})

        start_text = request.url.params["start"]
        end_text = request.url.params["end"]
        self.request_windows.append((start_text, end_text))
        if self.mode == "unavailable":
            return httpx.Response(503, text=UPSTREAM_FAILURE_MARKER)

        start = datetime.strptime(start_text, "%Y%m%d").date()
        end = datetime.strptime(end_text, "%Y%m%d").date()
        parameters: dict[str, dict[str, float]] = {
            "PRECTOTCORR": {},
            "T2M": {},
            "T2M_MAX": {},
        }
        current = start
        index = 0
        while current <= end:
            key = current.strftime("%Y%m%d")
            parameters["PRECTOTCORR"][key] = (
                -999.0 if self.mode == "partial" and index == 1 else 2.5
            )
            parameters["T2M"][key] = 27.0 + index % 4
            parameters["T2M_MAX"][key] = 33.0 + index % 3
            current += timedelta(days=1)
            index += 1

        return httpx.Response(
            200,
            json={
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        float(request.url.params["longitude"]),
                        float(request.url.params["latitude"]),
                    ],
                },
                "properties": {"parameter": parameters},
                "header": {
                    "title": "Synthetic NASA POWER daily source",
                    "api": {"name": "POWER Daily API", "version": "NY-10-synthetic"},
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
                    "T2M": {
                        "units": "C",
                        "longname": "Temperature at 2 Meters",
                        "source": "MERRA2",
                    },
                    "T2M_MAX": {
                        "units": "C",
                        "longname": "Maximum Temperature at 2 Meters",
                        "source": "MERRA2",
                    },
                },
                "times": {},
            },
        )


def _require_local_test_uri(uri: str) -> None:
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "mongodb"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or "," in parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("NY-10 integration requires a direct, credential-free local Mongo URI")


def configured_test_mongodb_uri() -> str:
    """Never inherit a development/remote URI or mutate an unknown database."""

    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to a direct local MongoDB listener")
    _require_local_test_uri(uri)
    return uri


@asynccontextmanager
async def isolated_mongo_app(
    mongodb_uri: str,
    nasa: SyntheticNASAPower,
) -> AsyncIterator[FastAPI]:
    """Run the real app against a unique test database and drop only that name."""

    _require_local_test_uri(mongodb_uri)
    database_name = f"ny10_test_{uuid4().hex}"
    assert database_name.startswith("ny10_test_")
    settings = Settings(
        _env_file=None,
        environment="test",
        mongodb_uri=SecretStr(mongodb_uri),
        mongodb_database_name=database_name,
        auth_cookie_secure=False,
        auth_session_lifetime_seconds=3_600,
        cors_allowed_origins=FRONTEND_ORIGIN,
        csrf_secret=SecretStr(CSRF_TEST_SECRET),
        location_hash_secret=SecretStr(LOCATION_TEST_SECRET),
    )
    app = create_app(
        settings,
        nasa_http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(nasa.handle)
        ),
    )

    async with app.router.lifespan_context(app):
        mongo: MongoConnection = app.state.mongo
        try:
            if not await mongo.is_ready():
                raise AssertionError("The explicitly configured local NY-10 MongoDB is unavailable")
            assert app.state.settings.environment == "test"
            assert mongo.database.name == database_name
            assert await SupportedLocationRepository().seed_missing() == 3
            crop_counts = await CropCatalogRepository().seed_missing()
            assert crop_counts["crops"] == 8
            assert await FarmReferenceRepository().seed_missing() == 8
            yield app
        finally:
            if await mongo.is_ready():
                await mongo.client.drop_database(database_name)


async def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.get("/api/v1/auth/csrf", headers={"Origin": FRONTEND_ORIGIN})
    assert response.status_code == 204
    token = client.cookies.get(AUTH_CSRF_COOKIE_NAME)
    assert token is not None
    return {"Origin": FRONTEND_ORIGIN, "X-CSRF-Token": token}


async def register_and_login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": SYNTHETIC_PASSWORD},
        headers=await csrf_headers(client),
    )
    assert registration.status_code == 201
    assert set(registration.json()) == {"id", "email"}
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": SYNTHETIC_PASSWORD},
        headers=await csrf_headers(client),
    )
    assert login.status_code == 204
    assert client.cookies.get(AUTH_COOKIE_NAME)
    identity = await client.get("/api/v1/auth/me")
    assert identity.status_code == 200
    assert identity.json() == registration.json()
    return registration.json()


def assert_public_payload_is_private(serialized: str) -> None:
    lowered = serialized.casefold()
    for forbidden in (
        "latitude",
        "longitude",
        "owner_user_id",
        "hashed_password",
        SYNTHETIC_PASSWORD.casefold(),
        MONGO_FAILURE_MARKER.casefold(),
        UPSTREAM_FAILURE_MARKER.casefold(),
        *PRIVATE_EJURA_COORDINATES,
    ):
        assert forbidden.casefold() not in lowered


def decision_signature(result: dict[str, Any]) -> tuple[Any, ...]:
    """Compare decisions while excluding live-vs-cached retrieval metadata."""

    scoring = result["scoring_result"]
    return (
        scoring["scoring_version"],
        scoring["ranking_mode"],
        scoring["ranking"]["status"],
        tuple(scoring["ranking"]["criteria_used"]),
        tuple(tuple(group) for group in scoring["ranking"]["rank_groups"]),
        tuple(
            (
                item["candidate"]["candidate_id"],
                tuple(
                    (criterion["criterion"], criterion["status"], criterion.get("rating"))
                    for criterion in item["criteria"]
                ),
            )
            for item in scoring["options"]
        ),
        result["decision_status"],
        result["candidate_pool_summary"],
    )


def test_authenticated_workflow_persists_reuses_and_enforces_ownership(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower()

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://testserver"
                ) as owner,
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://testserver"
                ) as other,
            ):
                assert (await owner.get("/api/v1/farms")).status_code == 401

                locations = await owner.get("/api/v1/farms/locations")
                references = await owner.get("/api/v1/farms/reference-options")
                history_crops = await owner.get("/api/v1/crops?usage=history")
                candidates = await owner.get("/api/v1/crops?usage=recommendation")
                assert all(
                    response.status_code == 200
                    for response in (locations, references, history_crops, candidates)
                )
                assert any(
                    item["location_key"] == "ejura" for item in locations.json()["locations"]
                )
                assert any(item["key"] == "loamy" for item in references.json()["soil_textures"])
                assert len(history_crops.json()["crops"]) == 8
                assert len(candidates.json()["crops"]) == 6
                assert_public_payload_is_private(locations.text)

                owner_user = await register_and_login(owner, "ama.ny10@example.com")
                other_user = await register_and_login(other, "kofi.ny10@example.com")
                assert owner_user["id"] != other_user["id"]

                forged_owner = await owner.post(
                    "/api/v1/farms",
                    json={**FARM_REQUEST, "owner_user_id": other_user["id"]},
                    headers=await csrf_headers(owner),
                )
                assert forged_owner.status_code == 422
                invalid_location = await owner.post(
                    "/api/v1/farms",
                    json={**FARM_REQUEST, "location_key": "not-supported"},
                    headers=await csrf_headers(owner),
                )
                assert invalid_location.status_code == 422
                assert nasa.request_windows == []

                farm_response = await owner.post(
                    "/api/v1/farms", json=FARM_REQUEST, headers=await csrf_headers(owner)
                )
                assert farm_response.status_code == 201
                farm = farm_response.json()
                farm_id = farm["id"]
                assert farm["schema_version"] == "farm-v2"
                assert farm["history_status"] == "complete"
                assert len(farm["crop_history"]) == 3
                assert [item["crop"]["key"] for item in farm["crop_history"]] == [
                    "maize",
                    "cowpea",
                    "maize",
                ]
                assert len(farm["declared_gaps"]) == 2
                assert farm["environmental_context"]["status"] == "ready"
                assert farm["environmental_context"]["period"]["start_date"] == CONTEXT_START
                assert farm["environmental_context"]["period"]["end_date"] == CONTEXT_END
                assert farm["environmental_context"]["snapshot_id"]
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW]
                assert_public_payload_is_private(farm_response.text)

                other_farm = await other.post(
                    "/api/v1/farms",
                    json={**FARM_REQUEST, "name": "Kofi synthetic comparison plot"},
                    headers=await csrf_headers(other),
                )
                assert other_farm.status_code == 201
                other_farm_id = other_farm.json()["id"]
                # The same location/period can reuse NY-6's shared snapshot.
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW]

                owner_list = await owner.get("/api/v1/farms")
                assert owner_list.status_code == 200
                assert [item["id"] for item in owner_list.json()] == [farm_id]
                detail = await owner.get(f"/api/v1/farms/{farm_id}")
                assert detail.status_code == 200
                assert detail.json()["crop_history"] == farm["crop_history"]

                renamed = await owner.patch(
                    f"/api/v1/farms/{farm_id}",
                    json={"name": "Ama synthetic plot updated"},
                    headers=await csrf_headers(owner),
                )
                assert renamed.status_code == 200
                assert renamed.json()["name"] == "Ama synthetic plot updated"
                assert (
                    renamed.json()["environmental_context"]["snapshot_id"]
                    == (farm["environmental_context"]["snapshot_id"])
                )
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW]

                obsolete_environment = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json={"start_date": "2024-01-01", "end_date": "2024-02-01"},
                    headers=await csrf_headers(owner),
                )
                obsolete_rotation = await owner.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json={"historical_seasons": [], "recommendation_seasons": []},
                    headers=await csrf_headers(owner),
                )
                assert obsolete_environment.status_code == obsolete_rotation.status_code == 422
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW]

                cached_context = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    headers=await csrf_headers(owner),
                )
                assert cached_context.status_code == 200
                context = cached_context.json()
                assert context["period"]["start_date"] == CONTEXT_START
                assert context["period"]["end_date"] == CONTEXT_END
                assert context["data_status"] == "cached"
                assert context["cache_action"] == "hit"
                assert context["snapshot_id"] == farm["environmental_context"]["snapshot_id"]
                assert len(context["indicators"]) == 3
                precipitation = next(
                    item
                    for item in context["indicators"]
                    if item["code"] == "seasonal_precipitation_total"
                )
                assert precipitation["source"] == "MERRA2"
                assert precipitation["source_products"] == ["MERRA2"]
                assert precipitation["coverage"]["missing_days"] == 0
                assert precipitation["coverage"]["coverage_percent"] == 100
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW]
                assert_public_payload_is_private(cached_context.text)

                nasa.mode = "unavailable"
                failed_refresh = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json={"force_refresh": True},
                    headers=await csrf_headers(owner),
                )
                assert failed_refresh.status_code == 200
                assert failed_refresh.json()["data_status"] == "cached"
                assert failed_refresh.json()["cache_action"] == "refresh_failed"
                assert failed_refresh.json()["refresh_attempted"] is True
                assert failed_refresh.json()["snapshot_id"] == context["snapshot_id"]
                assert len(nasa.request_windows) == 2
                assert UPSTREAM_FAILURE_MARKER not in failed_refresh.text
                nasa.mode = "complete"

                started = time.perf_counter()
                recommendation = await owner.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=recommendation_request(prioritize_water=True),
                    headers=await csrf_headers(owner),
                )
                elapsed = time.perf_counter() - started
                assert recommendation.status_code == 201
                assert elapsed < 60
                first_result = recommendation.json()
                assert first_result["schema_version"] == "ny38-result-v2"
                assert first_result["derived_context_period"]["start_date"] == CONTEXT_START
                assert first_result["derived_context_period"]["end_date"] == CONTEXT_END
                assert first_result["history_event_snapshots"]
                assert len(first_result["history_event_snapshots"]) == 3
                assert first_result["environmental_snapshot_ids"] == [context["snapshot_id"]]
                assert first_result["context_provenance"]["data_status"] == "cached"
                assert first_result["climate_reference_provenance"] is None
                assert first_result["climate_features"] == []
                assert first_result["baseline_status"] == "deferred"
                assert first_result["decision_status"] == "ranked_provisional"
                assert first_result["scoring_result"]["ranking"]["status"] == "ranked"
                assert first_result["scoring_result"]["ranking_mode"] == "water_soil_fallback"
                assert first_result["scoring_result"]["ranking"]["criteria_used"] == [
                    "water_resilience"
                ]
                assert first_result["scoring_result"]["baseline_option"] is None
                assert first_result["candidate_pool_summary"]["total_generated"] == 216
                assert first_result["candidate_pool_summary"]["total_returned"] == 3
                assert len(first_result["scoring_result"]["options"]) == 3
                assert first_result["scoring_result"]["ranking"]["unranked_candidate_count"] > 0
                assert all(
                    "rice"
                    not in {event["crop"]["crop_id"] for event in option["candidate"]["events"]}
                    for option in first_result["scoring_result"]["options"]
                )
                assert first_result["future_window_summary"]["fully_scheduled_count"] == 0
                assert len(nasa.request_windows) == 2
                assert_public_payload_is_private(recommendation.text)

                repeated = await owner.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=recommendation_request(prioritize_water=True),
                    headers=await csrf_headers(owner),
                )
                assert repeated.status_code == 201
                second_result = repeated.json()
                assert decision_signature(first_result) == decision_signature(second_result)
                assert (
                    first_result["environmental_snapshot_ids"]
                    == (second_result["environmental_snapshot_ids"])
                )
                assert len(nasa.request_windows) == 2
                assert await EnvironmentalSnapshot.get_pymongo_collection().count_documents({}) == 1

                history = await owner.get(f"/api/v1/farms/{farm_id}/rotation-results")
                assert history.status_code == 200
                assert len(history.json()) == 2
                assert {item["id"] for item in history.json()} == {
                    first_result["id"],
                    second_result["id"],
                }
                saved_detail = await owner.get(
                    f"/api/v1/farms/{farm_id}/rotation-results/{first_result['id']}"
                )
                assert saved_detail.status_code == 200
                assert saved_detail.json()["id"] == first_result["id"]
                assert_public_payload_is_private(history.text)
                assert_public_payload_is_private(saved_detail.text)

                assert [item["id"] for item in (await other.get("/api/v1/farms")).json()] == [
                    other_farm_id
                ]
                assert (await other.get(f"/api/v1/farms/{farm_id}")).status_code == 404
                assert (
                    await other.patch(
                        f"/api/v1/farms/{farm_id}",
                        json={"name": "forged update"},
                        headers=await csrf_headers(other),
                    )
                ).status_code == 404
                assert (
                    await other.get(f"/api/v1/farms/{farm_id}/rotation-results")
                ).status_code == 404
                assert (
                    await other.get(
                        f"/api/v1/farms/{other_farm_id}/rotation-results/{first_result['id']}"
                    )
                ).status_code == 404
                foreign_context = await other.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    headers=await csrf_headers(other),
                )
                foreign_generation = await other.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=recommendation_request(),
                    headers=await csrf_headers(other),
                )
                assert foreign_context.status_code == foreign_generation.status_code == 404
                assert len(nasa.request_windows) == 2

                owner_session = owner.cookies.get(AUTH_COOKIE_NAME)
                assert owner_session is not None
                stored = await AccessToken.find_one({"token": owner_session})
                assert stored is not None
                stored.created_at = datetime.now(UTC) - timedelta(hours=2)
                await stored.save()
                assert (await owner.get("/api/v1/auth/me")).status_code == 401
                assert (await owner.get("/api/v1/farms")).status_code == 401
                relogin = await owner.post(
                    "/api/v1/auth/login",
                    json={"email": "ama.ny10@example.com", "password": SYNTHETIC_PASSWORD},
                    headers=await csrf_headers(owner),
                )
                assert relogin.status_code == 204
                new_session = owner.cookies.get(AUTH_COOKIE_NAME)
                assert new_session is not None
                logout = await owner.post("/api/v1/auth/logout", headers=await csrf_headers(owner))
                assert logout.status_code == 204
                assert (await owner.get("/api/v1/auth/me")).status_code == 401
                assert await AccessToken.find_one({"token": new_session}) is None

                collection = app.state.mongo.database[ROTATION_RESULTS_COLLECTION_NAME]
                assert await collection.count_documents({"farm_id": PydanticObjectId(farm_id)}) == 2

        assert SYNTHETIC_PASSWORD not in caplog.text
        assert UPSTREAM_FAILURE_MARKER not in caplog.text
        assert all(point not in caplog.text for point in PRIVATE_EJURA_COORDINATES)

    asyncio.run(run())


def test_partial_values_remain_missing_in_persisted_context() -> None:
    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower(mode="partial")

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                await register_and_login(client, "partial.ny10@example.com")
                farm = await client.post(
                    "/api/v1/farms", json=FARM_REQUEST, headers=await csrf_headers(client)
                )
                assert farm.status_code == 201
                assert farm.json()["environmental_context"]["status"] == "partial"
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW]
                response = await client.post(
                    f"/api/v1/farms/{farm.json()['id']}/environmental-context",
                    headers=await csrf_headers(client),
                )
                assert response.status_code == 200
                body = response.json()
                assert body["context_status"] == "partial"
                assert body["data_status"] == "cached"
                precipitation = next(
                    item
                    for item in body["indicators"]
                    if item["code"] == "seasonal_precipitation_total"
                )
                expected = (
                    date.fromisoformat(CONTEXT_END) - date.fromisoformat(CONTEXT_START)
                ).days + 1
                assert precipitation["status"] == "partial"
                assert precipitation["coverage"]["expected_days"] == expected
                assert precipitation["coverage"]["valid_days"] == expected - 1
                assert precipitation["coverage"]["missing_days"] == 1
                assert precipitation["value"] == 2.5 * (expected - 1)
                assert precipitation["value"] != 0
                assert len(nasa.request_windows) == 1
                assert_public_payload_is_private(response.text)

    asyncio.run(run())


def test_absent_nasa_snapshot_stays_unavailable_and_unranked() -> None:
    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower(mode="unavailable")

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                await register_and_login(client, "unavailable.ny10@example.com")
                farm = await client.post(
                    "/api/v1/farms", json=FARM_REQUEST, headers=await csrf_headers(client)
                )
                assert farm.status_code == 201
                farm_id = farm.json()["id"]
                assert farm.json()["environmental_context"]["status"] == "unavailable"
                assert farm.json()["environmental_context"]["snapshot_id"] is None
                assert await EnvironmentalSnapshot.get_pymongo_collection().count_documents({}) == 0

                context = await client.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    headers=await csrf_headers(client),
                )
                assert context.status_code == 200
                assert context.json()["data_status"] == "unavailable"
                assert context.json()["error_code"] == "NASA_UPSTREAM_ERROR"
                assert all(item["value"] is None for item in context.json()["indicators"])
                assert_public_payload_is_private(context.text)

                result = await client.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=recommendation_request(),
                    headers=await csrf_headers(client),
                )
                assert result.status_code == 201
                body = result.json()
                assert body["environmental_snapshot_ids"] == []
                assert body["decision_status"] == "unavailable"
                assert body["scoring_result"]["ranking"]["status"] == "withheld"
                assert body["scoring_result"]["options"] == []
                assert UPSTREAM_FAILURE_MARKER not in result.text
                assert_public_payload_is_private(result.text)

    asyncio.run(run())


def test_incomplete_history_is_saved_but_workflow_requires_review() -> None:
    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower()

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                await register_and_login(client, "incomplete.ny10@example.com")
                draft = {
                    **FARM_REQUEST,
                    "history_status": "needs_review",
                    "crop_history": [],
                    "declared_gaps": [],
                }
                created = await client.post(
                    "/api/v1/farms", json=draft, headers=await csrf_headers(client)
                )
                assert created.status_code == 201
                assert created.json()["environmental_context"]["status"] == "needs_review"
                assert nasa.request_windows == []
                farm_id = created.json()["id"]
                context = await client.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    headers=await csrf_headers(client),
                )
                recommendation = await client.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=recommendation_request(),
                    headers=await csrf_headers(client),
                )
                assert context.status_code == recommendation.status_code == 409
                assert nasa.request_windows == []

    asyncio.run(run())


def test_mongo_lookup_failure_maps_to_safe_api_error(caplog: pytest.LogCaptureFixture) -> None:
    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower()

    class FailingFarmRepository:
        async def get_by_owner(self, **_kwargs: object) -> None:
            raise PyMongoError(MONGO_FAILURE_MARKER)

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                await register_and_login(client, "mongo.failure.ny10@example.com")
                app.dependency_overrides[get_farm_repository] = lambda: FailingFarmRepository()
                try:
                    response = await client.post(
                        f"/api/v1/farms/{PydanticObjectId()}/environmental-context",
                        headers=await csrf_headers(client),
                    )
                finally:
                    app.dependency_overrides.pop(get_farm_repository, None)
                assert response.status_code == 503
                assert "temporarily unavailable" in response.text
                assert MONGO_FAILURE_MARKER not in response.text
                assert MONGO_FAILURE_MARKER not in caplog.text
                assert nasa.request_windows == []
                assert_public_payload_is_private(response.text)

    asyncio.run(run())


def test_sourced_synthetic_stage_round_trips_through_mongo_result() -> None:
    """A complete test-only stage can use a second cached POWER reference.

    These dates and stage durations are synthetic contract fixtures. They are
    inserted only into the isolated database and never become pilot evidence.
    """

    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower()

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            first_calendar_year = datetime.now(UTC).year + 1
            maize = await Crop.find_one({"crop_key": "maize"})
            assert maize is not None and maize.id is not None
            seeded_generic = await CropProfileRevision.find_one(
                {
                    "crop_id": maize.id,
                    "variety_key": None,
                    "production_system_key": None,
                    "is_active": True,
                }
            )
            assert seeded_generic is not None
            seeded_generic.is_active = False
            await seeded_generic.save()
            source = SourceEvidence(
                source_url="https://example.org/ny40-synthetic-stage-test",
                source_title="Synthetic local integration fixture",
                source_confidence="low",
                pilot_transferability="low",
                applicability="Test database only; no agronomic claim.",
                limitations="Fabricated timing solely for serialization and API verification.",
                validation_status="provisional",
            )
            profile = CropProfileRevision(
                crop_id=maize.id,
                revision=2,
                is_active=True,
                published_at=datetime.now(UTC),
                evidence_status="provisional",
                maturity_days=MaturityEvidence(
                    value=MaturityRange(
                        min_days=20,
                        max_days=20,
                        meaning="planting_to_harvest",
                        endpoint_verified=True,
                    ),
                    source=source,
                ),
                growth_stages=[
                    GrowthStage(
                        stage_key="synthetic-water-stage",
                        start_offset_days=EvidenceValue(
                            value={"min_days": 0, "max_days": 0},
                            unit="days",
                            source=source,
                        ),
                        duration_days=EvidenceValue(
                            value={"min_days": 2, "max_days": 2},
                            unit="days",
                            source=source,
                        ),
                        sensitivity=EvidenceValue(
                            value={"factor": "water_shortage", "direction": "sensitive"},
                            source=source,
                        ),
                    )
                ],
            )
            await profile.insert()
            await CropCalendar(
                calendar_version="synthetic-march-v1",
                is_active=True,
                published_at=datetime.now(UTC),
                location_key="ejura",
                crop_id=maize.id,
                profile_revision_id=profile.id,
                season_key="synthetic-march",
                planting_window=PlantingWindow(
                    start_month_day="03-01",
                    end_month_day="03-01",
                    crosses_year=False,
                    valid_from_year=first_calendar_year,
                    valid_to_year=first_calendar_year + 3,
                ),
                evidence=source,
                status="provisional",
            ).insert()

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                await register_and_login(client, "stage.ny40@example.com")
                farm = await client.post(
                    "/api/v1/farms", json=FARM_REQUEST, headers=await csrf_headers(client)
                )
                assert farm.status_code == 201
                farm_id = farm.json()["id"]
                generated = await client.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json={},
                    headers=await csrf_headers(client),
                )
                assert generated.status_code == 201
                body = generated.json()
                assert nasa.request_windows == [CONTEXT_POWER_WINDOW, ("19910101", "20201231")]
                assert body["climate_reference_provenance"]["snapshot_id"]
                assert body["climate_reference_provenance"]["start_date"] == "1991-01-01"
                assert body["future_window_summary"]["fully_scheduled_count"] >= 1
                assessed = [
                    feature
                    for feature in body["climate_features"]
                    if feature["status"] == "assessed"
                ]
                assert assessed
                assert all(feature["units"] == "days" for feature in assessed)
                assert all(feature["complete_years_per_placement"] == 30 for feature in assessed)
                assert body["decision_status"] == "ranked_provisional"
                assert body["scoring_result"]["ranking"]["status"] == "ranked"
                assert len(body["scoring_result"]["options"]) == 3
                saved = await client.get(f"/api/v1/farms/{farm_id}/rotation-results/{body['id']}")
                assert saved.status_code == 200
                saved_features = saved.json()["climate_features"]
                current_features = body["climate_features"]
                assert len(saved_features) == len(current_features)
                for saved_feature, current_feature in zip(
                    saved_features, current_features, strict=True
                ):
                    # BSON datetimes have millisecond precision; the response
                    # immediately after insert may still show microseconds.
                    saved_time = datetime.fromisoformat(saved_feature["snapshot_retrieved_at"])
                    original_time = datetime.fromisoformat(current_feature["snapshot_retrieved_at"])
                    assert abs((saved_time - original_time).total_seconds()) < 0.001
                    assert {
                        key: value
                        for key, value in saved_feature.items()
                        if key != "snapshot_retrieved_at"
                    } == {
                        key: value
                        for key, value in current_feature.items()
                        if key != "snapshot_retrieved_at"
                    }
                assert saved.json()["climate_reference_ids"] == body["climate_reference_ids"]
                assert await EnvironmentalSnapshot.get_pymongo_collection().count_documents({}) == 2
                assert_public_payload_is_private(generated.text)

    asyncio.run(run())


def test_synthetic_profile_has_no_product_evidence_claim() -> None:
    assert PROFILE_ID == "ny10-synthetic-farm-v2"
    assert PROFILE_STATUS == "synthetic-test-data-only"
    assert len(HISTORY_EVENTS) == 3
    assert len(DECLARED_GAPS) == 2
    assert FARM_REQUEST["location_key"] == "ejura"
    assert recommendation_request() == {}
    assert set(recommendation_request(prioritize_water=True)) == {"priority_adjustment"}
