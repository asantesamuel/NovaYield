"""Opt-in end-to-end checks for the authenticated, persisted NovaYield workflow.

The API and MongoDB persistence are real. Only NASA's HTTP boundary is mocked so
these checks are repeatable and never depend on NASA availability or send farm
coordinates over the network.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
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
from app.models.environmental_snapshots import EnvironmentalSnapshot
from app.models.rotation_results import ROTATION_RESULTS_COLLECTION_NAME
from app.repositories.supported_locations import SupportedLocationRepository
from app.services.authentication import AUTH_COOKIE_NAME, AUTH_CSRF_COOKIE_NAME

from .demo_profile import (
    FARM_REQUEST,
    PAST_SEASONS,
    PROFILE_ID,
    PROFILE_STATUS,
    SYNTHETIC_PASSWORD,
    recommendation_request,
)

FRONTEND_ORIGIN = "http://localhost:5173"
CSRF_TEST_SECRET = "ny10-csrf-test-secret-with-more-than-thirty-two-bytes"
LOCATION_TEST_SECRET = "ny10-location-hash-test-secret-with-more-than-32-bytes"
MONGO_FAILURE_MARKER = "mongodb://ny10-private-user:ny10-private-password@private.invalid"
UPSTREAM_FAILURE_MARKER = "ny10-upstream-private-diagnostic-must-not-be-returned"
PRIVATE_EJURA_COORDINATES = ("7.3856", "-1.3562")


class SyntheticNASAPower:
    """Return deterministic NASA-shaped responses without making a network call."""

    def __init__(self, mode: Literal["complete", "partial", "unavailable"] = "complete") -> None:
        self.mode = mode
        # Keep only the request windows for assertions; do not retain/log coordinates.
        self.request_windows: list[tuple[str, str]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Act as the upstream HTTP endpoint used by the real NASA adapter."""

        endpoint = httpx.URL(NASA_POWER_DAILY_ENDPOINT)
        if (
            request.url.scheme != endpoint.scheme
            or request.url.host != endpoint.host
            or request.url.path != endpoint.path
        ):
            return httpx.Response(404, json={"error": "Unexpected mocked URL"})

        params = request.url.params
        start_text = params["start"]
        end_text = params["end"]
        self.request_windows.append((start_text, end_text))

        if self.mode == "unavailable":
            # The production adapter ignores upstream bodies on errors. The marker
            # proves a provider diagnostic cannot leak through the public response.
            return httpx.Response(
                503,
                text=f"provider failure: {UPSTREAM_FAILURE_MARKER}",
            )

        start = datetime.strptime(start_text, "%Y%m%d").date()
        end = datetime.strptime(end_text, "%Y%m%d").date()
        dates: list[date] = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)

        daily_parameters: dict[str, dict[str, float]] = {
            "PRECTOTCORR": {},
            "T2M": {},
            "T2M_MAX": {},
        }
        for index, day in enumerate(dates):
            day_key = day.strftime("%Y%m%d")
            daily_parameters["PRECTOTCORR"][day_key] = (
                -999.0 if self.mode == "partial" and index == 1 else 2.5
            )
            daily_parameters["T2M"][day_key] = 27.0 + index
            daily_parameters["T2M_MAX"][day_key] = 33.0 + index

        query_latitude = float(params["latitude"])
        query_longitude = float(params["longitude"])
        return httpx.Response(
            200,
            json={
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [query_longitude, query_latitude],
                },
                "properties": {"parameter": daily_parameters},
                "header": {
                    "title": "Synthetic NASA POWER Daily Source Native Resolution",
                    "api": {"name": "POWER Daily API", "version": "NY-10-test"},
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


@asynccontextmanager
async def isolated_mongo_app(
    mongodb_uri: str,
    nasa: SyntheticNASAPower,
) -> AsyncIterator[FastAPI]:
    """Start the actual app against one uniquely named, disposable Mongo database.

    The generated database name is the safety boundary: teardown drops only this
    NY-10-specific database, never the database named in the connection URI.
    """

    database_name = f"ny10_test_{uuid4().hex}"
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
            # Do not silently fall back to a development database when test Mongo is down.
            if not await mongo.is_ready():
                raise AssertionError("The explicitly configured NY-10 test MongoDB is unavailable")
            inserted = await SupportedLocationRepository().seed_missing()
            assert inserted == 3
            yield app
        finally:
            if await mongo.is_ready():
                await mongo.client.drop_database(database_name)


def configured_test_mongodb_uri() -> str:
    """Require an explicit test database instead of using the app's development default."""

    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run NY-10 real-Mongo integration tests")
    return uri


async def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Fetch the readable CSRF cookie, then echo it in the required request header."""

    response = await client.get(
        "/api/v1/auth/csrf",
        headers={"Origin": FRONTEND_ORIGIN},
    )
    assert response.status_code == 204
    csrf_token = client.cookies.get(AUTH_CSRF_COOKIE_NAME)
    assert csrf_token is not None
    return {"Origin": FRONTEND_ORIGIN, "X-CSRF-Token": csrf_token}


async def register_and_login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    """Exercise the real JSON registration and cookie-login API for one test user."""

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
    """Check public responses do not reveal the catalog point or private internals."""

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


def scoring_signature(result: dict[str, Any]) -> tuple[Any, ...]:
    """Compare recommendation decisions while excluding changing retrieval metadata."""

    scoring = result["scoring_result"]
    option_signature = tuple(
        (
            option["candidate"]["candidate_id"],
            tuple(
                (item["criterion"], item["status"], item.get("rating"))
                for item in option["criteria"]
            ),
        )
        for option in scoring["options"]
    )
    baseline = scoring.get("baseline_option")
    baseline_id = baseline["candidate"]["candidate_id"] if baseline else None
    selected_weights = tuple(
        (item["criterion"], item["percent"])
        for item in scoring["selected_weights"]["normalized_weights"]
    )
    return (
        scoring["scoring_version"],
        scoring["ranking_mode"],
        tuple(scoring["ranking"]["criteria_used"]),
        tuple(tuple(group) for group in scoring["ranking"]["rank_groups"]),
        selected_weights,
        baseline_id,
        option_signature,
    )


def test_authenticated_workflow_persists_reuses_and_enforces_ownership(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Run account → farm → NASA → indicators → ranking → saved history end to end."""

    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower()

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as owner,
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as other,
            ):
                # Unauthenticated requests are rejected before any farm is disclosed.
                assert (await owner.get("/api/v1/farms")).status_code == 401

                catalog = await owner.get("/api/v1/farms/locations")
                assert catalog.status_code == 200
                assert any(item["location_key"] == "ejura" for item in catalog.json()["locations"])
                assert_public_payload_is_private(catalog.text)

                owner_user = await register_and_login(owner, "ny10-owner@example.com")
                other_user = await register_and_login(other, "ny10-other@example.com")
                assert owner_user["id"] != other_user["id"]

                # The API rejects client-supplied ownership; the authenticated user sets it.
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

                farm_response = await owner.post(
                    "/api/v1/farms",
                    json=FARM_REQUEST,
                    headers=await csrf_headers(owner),
                )
                assert farm_response.status_code == 201
                farm = farm_response.json()
                farm_id = farm["id"]
                assert farm["location"] == {"location_key": "ejura", "label": "Ejura"}
                assert_public_payload_is_private(farm_response.text)

                other_farm_response = await other.post(
                    "/api/v1/farms",
                    json={**FARM_REQUEST, "name": "Other synthetic farm"},
                    headers=await csrf_headers(other),
                )
                assert other_farm_response.status_code == 201
                other_farm_id = other_farm_response.json()["id"]

                owner_list = await owner.get("/api/v1/farms")
                assert owner_list.status_code == 200
                assert [item["id"] for item in owner_list.json()] == [farm_id]
                assert_public_payload_is_private(owner_list.text)

                own_farm = await owner.get(f"/api/v1/farms/{farm_id}")
                assert own_farm.status_code == 200
                assert own_farm.json()["id"] == farm_id

                updated_farm = await owner.patch(
                    f"/api/v1/farms/{farm_id}",
                    json={"name": "NY-10 synthetic farm updated"},
                    headers=await csrf_headers(owner),
                )
                assert updated_farm.status_code == 200
                assert updated_farm.json()["name"] == "NY-10 synthetic farm updated"

                first_period = PAST_SEASONS[0]
                environmental_request = {
                    "start_date": first_period["analysis_start_date"],
                    "end_date": first_period["analysis_end_date"],
                }
                invalid_period = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json={
                        "start_date": (datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
                        "end_date": (datetime.now(UTC).date() + timedelta(days=2)).isoformat(),
                    },
                    headers=await csrf_headers(owner),
                )
                assert invalid_period.status_code == 422
                assert nasa.request_windows == []

                live_context = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json=environmental_request,
                    headers=await csrf_headers(owner),
                )
                assert live_context.status_code == 200
                live_body = live_context.json()
                assert live_body["data_status"] == "live"
                assert live_body["cache_action"] == "miss"
                assert live_body["period"] == environmental_request
                assert len(live_body["indicators"]) == 3
                precipitation = next(
                    item
                    for item in live_body["indicators"]
                    if item["code"] == "seasonal_precipitation_total"
                )
                assert precipitation["source"] == "MERRA2"
                assert precipitation["source_scope"] == "parameter"
                assert precipitation["source_products"] == ["MERRA2"]
                assert precipitation["units"] == "mm/season"
                assert precipitation["coverage"]["expected_days"] == 3
                assert precipitation["coverage"]["valid_days"] == 3
                assert precipitation["coverage"]["coverage_percent"] == 100
                assert_public_payload_is_private(live_context.text)
                assert nasa.request_windows == [("20220401", "20220403")]

                cached_context = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json=environmental_request,
                    headers=await csrf_headers(owner),
                )
                assert cached_context.status_code == 200
                assert cached_context.json()["data_status"] == "cached"
                assert cached_context.json()["cache_action"] == "hit"
                assert nasa.request_windows == [("20220401", "20220403")]

                # An explicit refresh failure must keep the previous valid snapshot,
                # label it cached, and avoid returning the upstream diagnostic body.
                nasa.mode = "unavailable"
                refresh_fallback = await owner.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json={**environmental_request, "force_refresh": True},
                    headers=await csrf_headers(owner),
                )
                assert refresh_fallback.status_code == 200
                fallback_body = refresh_fallback.json()
                assert fallback_body["data_status"] == "cached"
                assert fallback_body["cache_action"] == "refresh_failed"
                assert fallback_body["error_code"] == "NASA_UPSTREAM_ERROR"
                assert fallback_body["refresh_attempted"] is True
                assert UPSTREAM_FAILURE_MARKER not in refresh_fallback.text
                assert_public_payload_is_private(refresh_fallback.text)
                nasa.mode = "complete"

                rotation_request = recommendation_request()
                started_at = time.perf_counter()
                recommendation = await owner.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=rotation_request,
                    headers=await csrf_headers(owner),
                )
                first_elapsed_seconds = time.perf_counter() - started_at
                assert recommendation.status_code == 201
                assert first_elapsed_seconds < 60
                first_result = recommendation.json()
                assert len(first_result["environmental_snapshot_ids"]) == 3
                assert first_result["scoring_result"]["scoring_version"] == "ny8-scoring-v4"
                assert first_result["scoring_result"]["ranking"]["status"] == "ranked"
                assert len(first_result["scoring_result"]["options"]) == 3
                assert first_result["scoring_result"]["baseline_option"] is not None
                assert all(
                    len(option["criteria"]) == 4
                    for option in first_result["scoring_result"]["options"]
                )
                assert first_result["candidate_pool_summary"]["total_returned"] == 4
                assert "NASA POWER" in recommendation.text
                assert "2022-04-01" in recommendation.text
                assert "cached" in recommendation.text
                assert_public_payload_is_private(recommendation.text)

                # The direct environmental request covered season 1. The first
                # recommendation fetches only seasons 2 and 3, not season 1 again.
                assert nasa.request_windows == [
                    ("20220401", "20220403"),
                    ("20220401", "20220403"),  # one failed explicit refresh
                    ("20220901", "20220903"),
                    ("20230401", "20230403"),
                ]
                snapshots = EnvironmentalSnapshot.get_pymongo_collection()
                assert await snapshots.count_documents({}) == 3

                repeated_recommendation = await owner.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=rotation_request,
                    headers=await csrf_headers(owner),
                )
                assert repeated_recommendation.status_code == 201
                second_result = repeated_recommendation.json()
                assert scoring_signature(first_result) == scoring_signature(second_result)
                assert (
                    first_result["environmental_snapshot_ids"]
                    == second_result["environmental_snapshot_ids"]
                )
                assert nasa.request_windows[-3:] == [
                    ("20220401", "20220403"),
                    ("20220901", "20220903"),
                    ("20230401", "20230403"),
                ]
                assert len(nasa.request_windows) == 4
                assert await snapshots.count_documents({}) == 3

                history = await owner.get(f"/api/v1/farms/{farm_id}/rotation-results")
                assert history.status_code == 200
                assert len(history.json()) == 2
                assert {item["id"] for item in history.json()} == {
                    first_result["id"],
                    second_result["id"],
                }
                assert all(item["farm_id"] == farm_id for item in history.json())
                assert_public_payload_is_private(history.text)

                detail = await owner.get(
                    f"/api/v1/farms/{farm_id}/rotation-results/{first_result['id']}"
                )
                assert detail.status_code == 200
                assert detail.json()["id"] == first_result["id"]
                assert_public_payload_is_private(detail.text)

                # User B gets an empty owner-scoped list and cannot access, mutate,
                # generate for, or retrieve the other user's farm/result identifiers.
                other_list = await other.get("/api/v1/farms")
                assert other_list.status_code == 200
                assert [item["id"] for item in other_list.json()] == [other_farm_id]
                assert (await other.get(f"/api/v1/farms/{farm_id}")).status_code == 404
                assert (
                    await other.patch(
                        f"/api/v1/farms/{farm_id}",
                        json={"name": "unauthorized change"},
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
                calls_before_idor_attempt = len(nasa.request_windows)
                foreign_generation = await other.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=rotation_request,
                    headers=await csrf_headers(other),
                )
                assert foreign_generation.status_code == 404
                assert len(nasa.request_windows) == calls_before_idor_attempt

                # Exercise the real Mongo-backed expiry check by aging the stored
                # token, avoiding a slow sleep and avoiding changes to auth code.
                owner_session = owner.cookies.get(AUTH_COOKIE_NAME)
                assert owner_session is not None
                stored_token = await AccessToken.find_one({"token": owner_session})
                assert stored_token is not None
                stored_token.created_at = datetime.now(UTC) - timedelta(hours=2)
                await stored_token.save()
                assert (await owner.get("/api/v1/auth/me")).status_code == 401
                assert (await owner.get("/api/v1/farms")).status_code == 401

                relogin = await owner.post(
                    "/api/v1/auth/login",
                    json={"email": "ny10-owner@example.com", "password": SYNTHETIC_PASSWORD},
                    headers=await csrf_headers(owner),
                )
                assert relogin.status_code == 204
                current_session = owner.cookies.get(AUTH_COOKIE_NAME)
                assert current_session is not None
                logout = await owner.post(
                    "/api/v1/auth/logout",
                    headers=await csrf_headers(owner),
                )
                assert logout.status_code == 204
                assert (await owner.get("/api/v1/auth/me")).status_code == 401
                assert await AccessToken.find_one({"token": current_session}) is None

                result_collection = app.state.mongo.database[ROTATION_RESULTS_COLLECTION_NAME]
                assert (
                    await result_collection.count_documents({"farm_id": PydanticObjectId(farm_id)})
                    == 2
                )

        # Log capture includes application diagnostics emitted during the real flow.
        assert SYNTHETIC_PASSWORD not in caplog.text
        assert UPSTREAM_FAILURE_MARKER not in caplog.text
        assert all(coordinate not in caplog.text for coordinate in PRIVATE_EJURA_COORDINATES)

    asyncio.run(run())


def test_partial_nasa_values_keep_missingness_and_coverage_visible() -> None:
    """A fill value stays missing; calculations use only valid daily observations."""

    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower(mode="partial")

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                await register_and_login(client, "ny10-partial@example.com")
                farm = await client.post(
                    "/api/v1/farms",
                    json=FARM_REQUEST,
                    headers=await csrf_headers(client),
                )
                assert farm.status_code == 201
                period = PAST_SEASONS[0]
                context = await client.post(
                    f"/api/v1/farms/{farm.json()['id']}/environmental-context",
                    json={
                        "start_date": period["analysis_start_date"],
                        "end_date": period["analysis_end_date"],
                    },
                    headers=await csrf_headers(client),
                )
                assert context.status_code == 200
                body = context.json()
                assert body["data_status"] == "live"
                precipitation = next(
                    item
                    for item in body["indicators"]
                    if item["code"] == "seasonal_precipitation_total"
                )
                assert precipitation["status"] == "partial"
                assert precipitation["coverage"] == {
                    "expected_days": 3,
                    "valid_days": 2,
                    "missing_days": 1,
                    "coverage_percent": 66.67,
                }
                assert precipitation["value"] == 5.0
                assert precipitation["value"] != 0
                assert any("not imputed" in warning for warning in precipitation["warnings"])
                assert_public_payload_is_private(context.text)

    asyncio.run(run())


def test_absent_nasa_fallback_returns_unavailable_and_withholds_rotation_rank() -> None:
    """An upstream miss without cache never becomes invented environmental values."""

    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower(mode="unavailable")

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                await register_and_login(client, "ny10-unavailable@example.com")
                farm = await client.post(
                    "/api/v1/farms",
                    json=FARM_REQUEST,
                    headers=await csrf_headers(client),
                )
                assert farm.status_code == 201
                farm_id = farm.json()["id"]
                period = PAST_SEASONS[0]
                context = await client.post(
                    f"/api/v1/farms/{farm_id}/environmental-context",
                    json={
                        "start_date": period["analysis_start_date"],
                        "end_date": period["analysis_end_date"],
                    },
                    headers=await csrf_headers(client),
                )
                assert context.status_code == 200
                environmental = context.json()
                assert environmental["data_status"] == "unavailable"
                assert environmental["error_code"] == "NASA_UPSTREAM_ERROR"
                assert environmental["indicators"]
                assert all(item["value"] is None for item in environmental["indicators"])
                assert all(
                    item["coverage"]["valid_days"] == 0 and item["coverage"]["missing_days"] == 3
                    for item in environmental["indicators"]
                )
                assert UPSTREAM_FAILURE_MARKER not in context.text
                assert_public_payload_is_private(context.text)

                recommendation = await client.post(
                    f"/api/v1/farms/{farm_id}/rotation-recommendations",
                    json=recommendation_request(),
                    headers=await csrf_headers(client),
                )
                assert recommendation.status_code == 201
                result = recommendation.json()
                assert result["environmental_snapshot_ids"] == []
                assert result["scoring_result"]["ranking"]["status"] == "withheld"
                assert result["scoring_result"]["options"] == []
                assert any(
                    "No alternative has comparable water evidence" in reason
                    for reason in result["scoring_result"]["ranking"]["reasons"]
                )
                assert "unavailable" in recommendation.text
                assert UPSTREAM_FAILURE_MARKER not in recommendation.text
                assert_public_payload_is_private(recommendation.text)

    asyncio.run(run())


def test_mongo_repository_failure_is_mapped_to_a_safe_api_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A simulated persistence failure cannot leak its connection-string details."""

    mongodb_uri = configured_test_mongodb_uri()
    nasa = SyntheticNASAPower()

    class FailingFarmRepository:
        async def get_by_owner(self, **_kwargs: object) -> None:
            raise PyMongoError(MONGO_FAILURE_MARKER)

    async def run() -> None:
        async with isolated_mongo_app(mongodb_uri, nasa) as app:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                await register_and_login(client, "ny10-mongo-failure@example.com")
                app.dependency_overrides[get_farm_repository] = lambda: FailingFarmRepository()
                try:
                    response = await client.post(
                        f"/api/v1/farms/{PydanticObjectId()}/environmental-context",
                        json={
                            "start_date": PAST_SEASONS[0]["analysis_start_date"],
                            "end_date": PAST_SEASONS[0]["analysis_end_date"],
                        },
                        headers=await csrf_headers(client),
                    )
                finally:
                    app.dependency_overrides.pop(get_farm_repository, None)

                assert response.status_code == 503
                assert "temporarily unavailable" in response.text
                assert MONGO_FAILURE_MARKER not in response.text
                assert nasa.request_windows == []
                assert_public_payload_is_private(response.text)
                assert MONGO_FAILURE_MARKER not in caplog.text

    asyncio.run(run())


def test_synthetic_profile_is_explicitly_test_only() -> None:
    """Guard against presenting test observations as validated NovaYield evidence."""

    assert PROFILE_ID == "ny10-synthetic-workflow-v1"
    assert PROFILE_STATUS == "synthetic-test-data-only"
    assert len(PAST_SEASONS) == 3
    assert FARM_REQUEST["location_key"] == "ejura"
    assert all("synthetic" in season["season_label"] for season in PAST_SEASONS)
