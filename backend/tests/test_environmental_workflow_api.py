"""HTTP contracts for saved-farm context and recommendation orchestration.

The old caller-supplied NASA and future-date request shape is deliberately
rejected. These tests use the actual routers, indicators and decision services
with in-memory repositories and a synthetic cached POWER response.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
from beanie import PydanticObjectId
from fastapi import FastAPI
from pymongo.errors import PyMongoError

from app.api.workflows import create_workflow_router, get_environmental_snapshot_service
from app.farms.catalog_seed_data import WATER_RESILIENCE_EVIDENCE
from app.farms.context_window import derive_context_period
from app.farms.contracts import LocationCoordinates
from app.farms.routes import (
    get_crop_catalog_repository,
    get_farm_repository,
    get_supported_location_repository,
)
from app.integrations.nasa.power import (
    DailyValue,
    DateCoverage,
    PowerParameterMetadata,
    PowerParameterSeries,
    PowerProviderMetadata,
    SeasonalSummary,
)
from app.models.crop_catalog import Crop, CropProfileRevision, DecisionTraits
from app.models.farms import CropHistoryEvent, Farm, FarmEnvironmentalContextState
from app.models.rotation_results import FarmDecisionInputSnapshot, RotationResult
from app.models.supported_locations import SupportedLocation
from app.models.users import User
from app.repositories.crop_catalog import CropCandidateBundle
from app.rotation_results.routes import get_rotation_result_repository
from app.services.environmental_snapshots import FreshnessAssessment, SnapshotRetrieval


def _dated_farm(owner_id: PydanticObjectId | None = None) -> Farm:
    history = [
        CropHistoryEvent(
            event_id=f"past-{order}",
            crop_id=PydanticObjectId(),
            crop_key_snapshot=crop,
            sequence_order=order,
            start_date=start,
            end_date=end,
        )
        for order, (crop, start, end) in enumerate(
            (
                ("maize", date(2023, 3, 15), date(2023, 7, 1)),
                ("cowpea", date(2023, 8, 1), date(2023, 10, 1)),
                ("groundnut", date(2024, 3, 1), date(2024, 6, 15)),
            ),
            1,
        )
    ]
    period = derive_context_period(history)
    assert period is not None
    now = datetime(2026, 11, 1, tzinfo=UTC)
    return Farm.model_construct(
        id=PydanticObjectId(),
        owner_user_id=owner_id or PydanticObjectId(),
        schema_version="farm-v2",
        revision=1,
        name="Synthetic owned plot",
        location_key="ejura",
        soil_texture_key="loamy",
        irrigation_access_key="none",
        history_status="complete",
        crop_history=history,
        current_plot_available=True,
        earliest_available_date=date(2027, 1, 1),
        environmental_context=FarmEnvironmentalContextState(status="pending", period=period),
        created_at=now,
        updated_at=now,
    )


def _location() -> SupportedLocation:
    return SupportedLocation.model_construct(
        location_key="ejura",
        label="Ejura",
        coordinates=LocationCoordinates(latitude=7.3856, longitude=-1.3562),
    )


def _parameter_series(code: str, start: date, end: date, value: float) -> PowerParameterSeries:
    days: list[DailyValue] = []
    day = start
    while day <= end:
        days.append(DailyValue(date=day, value=value))
        day += timedelta(days=1)
    units = "mm/day" if code == "PRECTOTCORR" else "°C"
    return PowerParameterSeries(
        metadata=PowerParameterMetadata(
            code=code,
            long_name=f"Synthetic {code}",
            source_units=units,
            normalized_units=units,
            source="synthetic NASA POWER source",
            spatial_resolution="synthetic resolution",
            fill_value=-999.0,
        ),
        daily_values=days,
        seasonal_summary=SeasonalSummary(
            method="sum" if code == "PRECTOTCORR" else "mean",
            value=value * len(days) if code == "PRECTOTCORR" else value,
            units="mm" if code == "PRECTOTCORR" else "°C",
            status="complete",
            coverage=DateCoverage(
                requested_start_date=start,
                requested_end_date=end,
                returned_start_date=start,
                returned_end_date=end,
                expected_days=len(days),
                valid_days=len(days),
                missing_days=0,
                coverage_percent=100,
            ),
        ),
    )


def _cached_retrieval(farm: Farm) -> SnapshotRetrieval:
    assert farm.environmental_context is not None
    period = farm.environmental_context.period
    assert period is not None
    snapshot = SimpleNamespace(
        id=PydanticObjectId(),
        identity=SimpleNamespace(start_date=period.start_date, end_date=period.end_date),
        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
        provider_metadata=PowerProviderMetadata(
            header_title="Synthetic NASA POWER response", source_products=["synthetic source"]
        ),
        parameters={
            "PRECTOTCORR": _parameter_series(
                "PRECTOTCORR", period.start_date, period.end_date, 5.0
            ),
            "T2M": _parameter_series("T2M", period.start_date, period.end_date, 27.0),
            "T2M_MAX": _parameter_series("T2M_MAX", period.start_date, period.end_date, 33.0),
        },
    )
    return SnapshotRetrieval(
        snapshot=snapshot,
        data_status="cached",
        cache_action="hit",
        freshness=FreshnessAssessment("unknown", 60.0, "No source refresh rule configured."),
        refresh_attempted=False,
    )


class FakeFarmRepository:
    def __init__(self, farm: Farm | None, *, error: Exception | None = None) -> None:
        self.farm = farm
        self.error = error
        self.owner_queries: list[tuple[PydanticObjectId, PydanticObjectId]] = []
        self.context_updates: list[FarmEnvironmentalContextState] = []
        self.update_error: Exception | None = None

    async def get_by_owner(
        self, *, farm_id: PydanticObjectId, owner_user_id: PydanticObjectId
    ) -> Farm | None:
        self.owner_queries.append((farm_id, owner_user_id))
        if self.error is not None:
            raise self.error
        if self.farm is None or self.farm.id != farm_id or self.farm.owner_user_id != owner_user_id:
            return None
        return self.farm

    async def set_environmental_context_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        expected_revision: int,
        context: FarmEnvironmentalContextState,
    ) -> Farm | None:
        if self.update_error is not None:
            raise self.update_error
        if (
            self.farm is None
            or farm_id != self.farm.id
            or owner_user_id != self.farm.owner_user_id
            or expected_revision != self.farm.revision
        ):
            return None
        self.context_updates.append(context)
        self.farm = self.farm.model_copy(update={"environmental_context": context})
        return self.farm


class FakeLocationRepository:
    def __init__(self, location: SupportedLocation | None = None) -> None:
        self.location = location or _location()
        self.lookups: list[str] = []

    async def get_by_key(self, key: str) -> SupportedLocation | None:
        self.lookups.append(key)
        return self.location


class FakeSnapshotService:
    def __init__(
        self, retrieval: SnapshotRetrieval | None = None, *, error: Exception | None = None
    ) -> None:
        self.retrieval = retrieval
        self.error = error
        self.requests: list[tuple[Any, bool]] = []

    async def retrieve(self, request: Any, *, force_refresh: bool = False) -> SnapshotRetrieval:
        self.requests.append((request, force_refresh))
        if self.error is not None:
            raise self.error
        assert self.retrieval is not None
        assert request.start_date == self.retrieval.snapshot.identity.start_date
        assert request.end_date == self.retrieval.snapshot.identity.end_date
        return self.retrieval


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.lookups: list[str] = []
        self.bundles = []
        for key in ("maize", "cowpea", "groundnut"):
            crop = Crop.model_construct(
                id=PydanticObjectId(),
                crop_key=key,
                common_name=key.title(),
                scientific_name=None,
                family=None,
                identity_source_url=f"https://example.org/synthetic-{key}",
                history_selectable=True,
                recommendation_candidate=True,
                catalog_status="active",
            )
            profile = CropProfileRevision.model_construct(
                id=PydanticObjectId(),
                crop_id=crop.id,
                revision=1,
                is_active=True,
                variety_key=None,
                production_system_key=None,
                evidence_status="provisional",
                decision_traits=DecisionTraits(
                    water_resilience_class=WATER_RESILIENCE_EVIDENCE[key]
                ),
            )
            self.bundles.append(
                CropCandidateBundle(crop=crop, active_profiles=(profile,), calendars=())
            )

    async def list_recommendation_candidates(self, *, location_key: str):
        self.lookups.append(location_key)
        return self.bundles


class FakeResultRepository:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.saved: list[RotationResult] = []

    async def create_for_farm(self, **kwargs: Any) -> RotationResult:
        if self.error is not None:
            raise self.error
        farm: Farm = kwargs["farm"]
        result = RotationResult.model_construct(
            id=PydanticObjectId(),
            schema_version="ny38-result-v2",
            owner_user_id=kwargs["owner_user_id"],
            farm_id=farm.id,
            created_at=datetime(2026, 11, 2, tzinfo=UTC),
            farm_inputs=FarmDecisionInputSnapshot.from_farm(farm),
            history_event_snapshots=tuple(farm.crop_history),
            baseline_status="deferred",
            **{key: value for key, value in kwargs.items() if key not in {"farm", "owner_user_id"}},
        )
        self.saved.append(result)
        return result


def _app(
    *,
    user_id: PydanticObjectId,
    farms: FakeFarmRepository,
    locations: FakeLocationRepository,
    snapshots: FakeSnapshotService,
    catalog: FakeCatalogRepository | None = None,
    results: FakeResultRepository | None = None,
) -> FastAPI:
    async def current_user() -> User:
        return User.model_construct(id=user_id, email="synthetic-farmer@example.org")

    app = FastAPI()
    app.include_router(create_workflow_router(current_user))
    catalog_value = catalog if catalog is not None else FakeCatalogRepository()
    results_value = results if results is not None else FakeResultRepository()
    app.dependency_overrides[get_farm_repository] = lambda: farms
    app.dependency_overrides[get_supported_location_repository] = lambda: locations
    app.dependency_overrides[get_environmental_snapshot_service] = lambda: snapshots
    app.dependency_overrides[get_crop_catalog_repository] = lambda: catalog_value
    app.dependency_overrides[get_rotation_result_repository] = lambda: results_value
    return app


def _post(app: FastAPI, path: str, json: Any = None) -> httpx.Response:
    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=json)

    return asyncio.run(call())


def test_environmental_route_authorizes_before_location_or_nasa_lookup() -> None:
    farm = _dated_farm()
    farms = FakeFarmRepository(farm)
    locations = FakeLocationRepository()
    snapshots = FakeSnapshotService(_cached_retrieval(farm))
    another_user_id = PydanticObjectId()
    app = _app(user_id=another_user_id, farms=farms, locations=locations, snapshots=snapshots)

    response = _post(app, f"/farms/{farm.id}/environmental-context")

    assert response.status_code == 404
    assert response.json() == {"detail": "Farm not found."}
    assert farms.owner_queries == [(farm.id, another_user_id)]
    assert locations.lookups == []
    assert snapshots.requests == []


def test_environmental_route_uses_saved_period_and_reports_cached_reuse() -> None:
    farm = _dated_farm()
    period = farm.environmental_context.period
    assert period is not None
    farms = FakeFarmRepository(farm)
    snapshots = FakeSnapshotService(_cached_retrieval(farm))
    app = _app(
        user_id=farm.owner_user_id,
        farms=farms,
        locations=FakeLocationRepository(),
        snapshots=snapshots,
    )

    first = _post(app, f"/farms/{farm.id}/environmental-context")
    second = _post(app, f"/farms/{farm.id}/environmental-context", {"force_refresh": True})

    assert first.status_code == second.status_code == 200
    body = first.json()
    assert body["farm_id"] == str(farm.id)
    assert body["location"] == {"location_key": "ejura", "label": "Ejura"}
    assert body["period"] == {
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "policy_version": period.policy_version,
    }
    assert body["context_status"] == "ready"
    assert body["data_status"] == "cached"
    assert body["cache_action"] == "hit"
    assert body["snapshot_id"] == second.json()["snapshot_id"]
    assert len(body["indicators"]) == 3
    assert all(item["status"] == "complete" for item in body["indicators"])
    assert [force for _, force in snapshots.requests] == [False, True]
    assert all(request.start_date == period.start_date for request, _ in snapshots.requests)
    assert all(request.end_date == period.end_date for request, _ in snapshots.requests)
    assert "7.3856" not in first.text
    assert "-1.3562" not in first.text


def test_environmental_route_withholds_legacy_and_incomplete_history_before_nasa() -> None:
    for changes in (
        {"schema_version": "farm-v1"},
        {"history_status": "needs_review"},
        {"environmental_context": FarmEnvironmentalContextState(status="needs_review")},
    ):
        original = _dated_farm()
        farm = original.model_copy(update=changes)
        snapshots = FakeSnapshotService(_cached_retrieval(original))
        app = _app(
            user_id=farm.owner_user_id,
            farms=FakeFarmRepository(farm),
            locations=FakeLocationRepository(),
            snapshots=snapshots,
        )
        response = _post(app, f"/farms/{farm.id}/environmental-context")
        assert response.status_code == 409
        assert "dated crop history" in response.json()["detail"]
        assert snapshots.requests == []


def test_obsolete_caller_supplied_dates_are_rejected_by_both_routes() -> None:
    farm = _dated_farm()
    snapshots = FakeSnapshotService(_cached_retrieval(farm))
    app = _app(
        user_id=farm.owner_user_id,
        farms=FakeFarmRepository(farm),
        locations=FakeLocationRepository(),
        snapshots=snapshots,
    )

    environmental = _post(
        app,
        f"/farms/{farm.id}/environmental-context",
        {"start_date": "2024-01-01", "end_date": "2024-02-01"},
    )
    recommendation = _post(
        app,
        f"/farms/{farm.id}/rotation-recommendations",
        {
            "historical_seasons": [{"analysis_start_date": "2024-01-01"}],
            "recommendation_seasons": [{"window_start": "2027-01-01"}],
        },
    )

    assert environmental.status_code == recommendation.status_code == 422
    assert snapshots.requests == []


def test_upstream_and_storage_failures_are_client_safe_and_do_not_undo_farm() -> None:
    farm = _dated_farm()
    farms = FakeFarmRepository(farm)
    secret_marker = "mongodb+srv://disposable-secret@private.invalid"
    snapshots = FakeSnapshotService(error=TimeoutError(secret_marker))
    app = _app(
        user_id=farm.owner_user_id,
        farms=farms,
        locations=FakeLocationRepository(),
        snapshots=snapshots,
    )
    response = _post(app, f"/farms/{farm.id}/environmental-context")
    assert response.status_code == 200
    assert response.json()["context_status"] == "unavailable"
    assert response.json()["data_status"] == "unavailable"
    assert response.json()["error_code"] == "NASA_UNAVAILABLE"
    assert secret_marker not in response.text
    assert farm.id == farms.farm.id

    farms = FakeFarmRepository(farm)
    farms.update_error = PyMongoError(secret_marker)
    app = _app(
        user_id=farm.owner_user_id,
        farms=farms,
        locations=FakeLocationRepository(),
        snapshots=FakeSnapshotService(_cached_retrieval(farm)),
    )
    storage = _post(app, f"/farms/{farm.id}/environmental-context")
    assert storage.status_code == 200
    assert storage.json()["data_status"] == "unavailable"
    assert secret_marker not in storage.text
    assert farms.farm.id == farm.id


def test_recommendation_route_checks_owner_and_history_before_nasa() -> None:
    farm = _dated_farm()
    snapshots = FakeSnapshotService(_cached_retrieval(farm))
    app = _app(
        user_id=PydanticObjectId(),
        farms=FakeFarmRepository(farm),
        locations=FakeLocationRepository(),
        snapshots=snapshots,
    )
    unauthorized = _post(app, f"/farms/{farm.id}/rotation-recommendations")
    assert unauthorized.status_code == 404
    assert snapshots.requests == []

    legacy = farm.model_copy(update={"schema_version": "farm-v1"})
    app = _app(
        user_id=farm.owner_user_id,
        farms=FakeFarmRepository(legacy),
        locations=FakeLocationRepository(),
        snapshots=snapshots,
    )
    incomplete = _post(app, f"/farms/{farm.id}/rotation-recommendations")
    assert incomplete.status_code == 409
    assert snapshots.requests == []


def test_recommendation_route_reuses_one_context_lookup_and_returns_safe_result() -> None:
    farm = _dated_farm()
    farms = FakeFarmRepository(farm)
    snapshots = FakeSnapshotService(_cached_retrieval(farm))
    catalog = FakeCatalogRepository()
    results = FakeResultRepository()
    app = _app(
        user_id=farm.owner_user_id,
        farms=farms,
        locations=FakeLocationRepository(),
        snapshots=snapshots,
        catalog=catalog,
        results=results,
    )

    response = _post(
        app,
        f"/farms/{farm.id}/rotation-recommendations",
        {
            "priority_adjustment": {
                "water_resilience": 70,
                "soil_health_potential": 10,
                "yield_stability_proxy": 10,
                "labor_feasibility": 10,
            }
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["farm_id"] == str(farm.id)
    assert body["decision_status"] == "ranked_provisional"
    assert body["scoring_result"]["ranking"]["status"] == "ranked"
    assert body["scoring_result"]["ranking_mode"] == "water_soil_fallback"
    assert body["scoring_result"]["ranking"]["criteria_used"] == ["water_resilience"]
    assert body["derived_context_period"]["start_date"] == (
        farm.environmental_context.period.start_date.isoformat()
    )
    assert body["context_provenance"]["data_status"] == "cached"
    assert body["context_provenance"]["cache_action"] == "hit"
    assert body["future_window_summary"]["fully_scheduled_count"] == 0
    assert body["candidate_pool_summary"]["total_generated"] == 27
    assert body["candidate_pool_summary"]["total_returned"] == 3
    assert len(body["scoring_result"]["options"]) == 3
    first_water = next(
        criterion
        for criterion in body["scoring_result"]["options"][0]["criteria"]
        if criterion["criterion"] == "water_resilience"
    )
    assert first_water["status"] == "assessed"
    assert first_water["confidence"] in {"low", "moderate"}
    assert first_water["evidence_references"]
    assert "provisional" in first_water["rationale"].lower()
    assert len(snapshots.requests) == 1  # no duplicate NASA lookup inside one workflow
    assert catalog.lookups == ["ejura"]
    assert len(results.saved) == 1
    assert results.saved[0].decision_inputs.scoring_request.farmer_priorities.water_resilience == 70
    assert "7.3856" not in response.text
    assert "-1.3562" not in response.text
    assert "owner_user_id" not in response.text


def test_recommendation_storage_failure_returns_safe_503() -> None:
    farm = _dated_farm()
    marker = "mongodb+srv://disposable-secret@private.invalid"
    app = _app(
        user_id=farm.owner_user_id,
        farms=FakeFarmRepository(farm),
        locations=FakeLocationRepository(),
        snapshots=FakeSnapshotService(_cached_retrieval(farm)),
        results=FakeResultRepository(error=PyMongoError(marker)),
    )
    response = _post(app, f"/farms/{farm.id}/rotation-recommendations")
    assert response.status_code == 503
    assert response.json()["detail"] == "The rotation result could not be saved. Please retry."
    assert marker not in response.text
