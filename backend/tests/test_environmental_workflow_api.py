"""Contract and ownership tests for farm-scoped environmental context."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from beanie import PydanticObjectId
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pymongo.errors import PyMongoError

from app.api.workflows import create_workflow_router
from app.decisions.rotation import RotationGenerationResult
from app.decisions.scoring import PriorityPoints, ScoringResult
from app.farms.contracts import LocationCoordinates
from app.farms.routes import FARM_NOT_FOUND_DETAIL
from app.integrations.nasa.power import (
    DailyValue,
    DateCoverage,
    PowerParameterMetadata,
    PowerParameterSeries,
    PowerProviderMetadata,
    PowerRequest,
    SeasonalSummary,
)
from app.models.environmental_snapshots import EnvironmentalSnapshot, SnapshotIdentity
from app.models.farms import Farm
from app.models.rotation_results import (
    FarmDecisionInputSnapshot,
    RotationDecisionInputs,
    RotationResult,
)
from app.models.supported_locations import SupportedLocation
from app.models.users import User
from app.schemas.decision_workflows import (
    EnvironmentalContextRequest,
    RotationRecommendationRequest,
)
from app.services.environmental_snapshots import (
    FreshnessAssessment,
    SnapshotRetrieval,
)


def make_farm(farm_id: PydanticObjectId, owner_id: PydanticObjectId) -> Farm:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Farm.model_construct(
        id=farm_id,
        owner_user_id=owner_id,
        name="Test farm",
        location_key="ejura",
        soil_texture="unknown",
        irrigation_access=None,
        previous_crops=None,
        current_practice=None,
        farmer_priorities={
            "water_resilience": 25,
            "soil_health_potential": 25,
            "yield_stability_proxy": 25,
            "labor_feasibility": 25,
        },
        created_at=now,
        updated_at=now,
    )


def make_location() -> SupportedLocation:
    return SupportedLocation.model_construct(
        location_key="ejura",
        label="Ejura",
        coordinates=LocationCoordinates(latitude=7.3856, longitude=-1.3562),
    )


def make_snapshot(request: PowerRequest) -> EnvironmentalSnapshot:
    expected_days = (request.end_date - request.start_date).days + 1
    daily_dates = [request.start_date + timedelta(days=offset) for offset in range(expected_days)]
    parameter_specs = (
        ("PRECTOTCORR", "mm/day", "mm/season", "sum", (12.0, 8.0)),
        ("T2M", "°C", "°C", "mean", (27.0, 28.0)),
        ("T2M_MAX", "°C", "°C", "mean", (33.0, 34.0)),
    )
    parameters = {}
    for code, input_units, summary_units, method, values in parameter_specs:
        value_by_date = values[:expected_days]
        parameters[code] = PowerParameterSeries(
            metadata=PowerParameterMetadata(
                code=code,
                long_name=code,
                source_units=input_units,
                normalized_units=input_units,
                source="NASA POWER test source",
                spatial_resolution="test resolution",
                fill_value=-999.0,
            ),
            daily_values=[
                DailyValue(date=day, value=value)
                for day, value in zip(daily_dates, value_by_date, strict=True)
            ],
            seasonal_summary=SeasonalSummary(
                method=method,
                value=(
                    sum(value_by_date)
                    if method == "sum"
                    else sum(value_by_date) / len(value_by_date)
                ),
                units=summary_units,
                status="complete",
                coverage=DateCoverage(
                    requested_start_date=request.start_date,
                    requested_end_date=request.end_date,
                    returned_start_date=request.start_date,
                    returned_end_date=request.end_date,
                    expected_days=expected_days,
                    valid_days=expected_days,
                    missing_days=0,
                    coverage_percent=100,
                ),
            ),
        )

    identity = SnapshotIdentity(
        location_key="a" * 64,
        parameters=tuple(sorted(parameters)),
        start_date=request.start_date,
        end_date=request.end_date,
        request_key="b" * 64,
    )
    return EnvironmentalSnapshot.model_construct(
        id=PydanticObjectId(),
        identity=identity,
        retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
        provider_metadata=PowerProviderMetadata(header_title="NASA POWER test"),
        parameters=parameters,
        request_contexts=[],
    )


class InMemoryFarmRepository:
    def __init__(self, farm: Farm | None) -> None:
        self.farm = farm
        self.queries: list[dict[str, PydanticObjectId]] = []

    async def get_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
    ) -> Farm | None:
        self.queries.append({"farm_id": farm_id, "owner_user_id": owner_user_id})
        if self.farm is None or self.farm.id != farm_id or self.farm.owner_user_id != owner_user_id:
            return None
        return self.farm


class InMemoryLocationRepository:
    async def get_by_key(self, _location_key: str) -> SupportedLocation:
        return make_location()


class InMemorySnapshotService:
    def __init__(
        self,
        retrieval: SnapshotRetrieval | None = None,
        *,
        retrieval_factory: Callable[[PowerRequest], SnapshotRetrieval] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.retrieval_factory = retrieval_factory
        self.error = error
        self.requests: list[tuple[PowerRequest, bool]] = []

    async def retrieve(
        self,
        request: PowerRequest,
        *,
        force_refresh: bool = False,
    ) -> SnapshotRetrieval:
        self.requests.append((request, force_refresh))
        if self.error is not None:
            raise self.error
        if self.retrieval_factory is not None:
            return self.retrieval_factory(request)
        assert self.retrieval is not None
        return self.retrieval


class InMemoryRotationResultRepository:
    def __init__(self, error: Exception | None = None) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.saved_result: RotationResult | None = None
        self.error = error

    async def create_for_farm(
        self,
        *,
        owner_user_id: PydanticObjectId,
        farm: Farm,
        decision_inputs: RotationDecisionInputs,
        candidate_generation: RotationGenerationResult,
        scoring_result: ScoringResult,
    ) -> RotationResult:
        if self.error is not None:
            raise self.error
        self.create_calls.append(
            {
                "owner_user_id": owner_user_id,
                "farm": farm,
                "decision_inputs": decision_inputs,
                "candidate_generation": candidate_generation,
                "scoring_result": scoring_result,
            }
        )
        self.saved_result = RotationResult.model_construct(
            id=PydanticObjectId(),
            schema_version="ny20-result-v1",
            owner_user_id=owner_user_id,
            farm_id=farm.id,
            created_at=datetime(2026, 1, 3, tzinfo=UTC),
            farm_inputs=FarmDecisionInputSnapshot.from_farm(farm),
            decision_inputs=decision_inputs,
            candidate_generation=candidate_generation,
            scoring_result=scoring_result,
        )
        return self.saved_result


def make_user(user_id: PydanticObjectId) -> User:
    return User.model_construct(id=user_id, email="farmer@example.com")


def make_retrieval(request: PowerRequest) -> SnapshotRetrieval:
    return SnapshotRetrieval(
        snapshot=make_snapshot(request),
        data_status="cached",
        cache_action="hit",
        freshness=FreshnessAssessment("unknown", 60.0, "No source refresh interval is configured."),
        refresh_attempted=False,
    )


def make_rotation_request(
    *,
    historical_seasons: tuple[dict[str, Any], ...] | None = None,
    recommendation_seasons: tuple[dict[str, Any], ...] | None = None,
) -> RotationRecommendationRequest:
    """Build a synthetic request with past NASA windows and separate future slots."""

    if historical_seasons is None:
        historical_seasons = (
            {
                "season_label": "2020 major",
                "analysis_start_date": "2020-04-01",
                "analysis_end_date": "2020-04-02",
                "planted_crop": "maize",
            },
            {
                "season_label": "2020 minor",
                "analysis_start_date": "2020-09-01",
                "analysis_end_date": "2020-09-02",
                "planted_crop": "cowpea",
            },
            {
                "season_label": "2021 major",
                "analysis_start_date": "2021-04-01",
                "analysis_end_date": "2021-04-02",
                "planted_crop": "yam",
            },
        )
    if recommendation_seasons is None:
        first_start = date.today() + timedelta(days=30)
        recommendation_seasons = tuple(
            {
                "season_label": f"future slot {order}",
                "window_start": first_start + timedelta(days=31 * (order - 1)),
                "window_end": first_start + timedelta(days=31 * (order - 1) + 29),
            }
            for order in range(1, 4)
        )
    return RotationRecommendationRequest(
        plot_reference="plot-a",
        historical_seasons=historical_seasons,
        recommendation_seasons=recommendation_seasons,
    )


def make_router_and_handler() -> tuple[Any, Any]:
    def current_active_user() -> User:
        return make_user(PydanticObjectId())

    router = create_workflow_router(current_active_user)
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/farms/{farm_id}/environmental-context"
    )
    return router, route.endpoint


def run_immediately(awaitable: Any) -> Any:
    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("An in-memory workflow handler unexpectedly suspended.")


def test_environmental_context_uses_owned_farm_and_private_catalog_point() -> None:
    owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), owner_id)
    farm_repository = InMemoryFarmRepository(farm)
    snapshot_request = PowerRequest(
        latitude=7.3856,
        longitude=-1.3562,
        start_date=date(2020, 4, 1),
        end_date=date(2020, 4, 2),
    )
    snapshot_service = InMemorySnapshotService(make_retrieval(snapshot_request))
    _, handler = make_router_and_handler()

    response = run_immediately(
        handler(
            farm_id=farm.id,
            request_body=EnvironmentalContextRequest(
                start_date=date(2020, 4, 1),
                end_date=date(2020, 4, 2),
            ),
            user=make_user(owner_id),
            farm_repository=farm_repository,
            location_repository=InMemoryLocationRepository(),
            snapshot_service=snapshot_service,
        )
    )
    body = response.model_dump(mode="json")

    assert body["farm_id"] == str(farm.id)
    assert body["location"] == {"location_key": "ejura", "label": "Ejura"}
    assert body["data_status"] == "cached"
    assert body["cache_action"] == "hit"
    assert body["indicators"][0]["value"] == 20.0
    assert len(body["indicators"]) == 3
    assert snapshot_service.requests[0][0].latitude == 7.3856
    assert snapshot_service.requests[0][0].longitude == -1.3562
    serialized = str(body).lower()
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "owner_user_id" not in serialized
    assert farm_repository.queries == [{"farm_id": farm.id, "owner_user_id": owner_id}]


def test_non_owned_farm_is_rejected_before_location_or_snapshot_lookup() -> None:
    other_owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), other_owner_id)
    farm_repository = InMemoryFarmRepository(farm)
    snapshot_service = InMemorySnapshotService(
        SnapshotRetrieval(
            snapshot=None,
            data_status="unavailable",
            cache_action="unavailable",
            freshness=FreshnessAssessment("unknown", None, "No stored snapshot exists."),
            refresh_attempted=False,
        )
    )
    _, handler = make_router_and_handler()

    with pytest.raises(HTTPException) as not_found:
        run_immediately(
            handler(
                farm_id=farm.id,
                request_body=EnvironmentalContextRequest(
                    start_date=date(2020, 4, 1),
                    end_date=date(2020, 4, 2),
                ),
                user=make_user(PydanticObjectId()),
                farm_repository=farm_repository,
                location_repository=InMemoryLocationRepository(),
                snapshot_service=snapshot_service,
            )
        )

    assert not_found.value.status_code == 404
    assert not_found.value.detail == FARM_NOT_FOUND_DETAIL
    assert snapshot_service.requests == []


def test_upstream_failure_is_returned_as_a_typed_unavailable_context() -> None:
    owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), owner_id)
    snapshot_service = InMemorySnapshotService(
        SnapshotRetrieval(
            snapshot=None,
            data_status="unavailable",
            cache_action="unavailable",
            freshness=FreshnessAssessment("unknown", None, "No persisted snapshot is available."),
            refresh_attempted=True,
            error_code="PowerTimeoutError",
            warnings=("NASA POWER request timed out.",),
        )
    )
    _, handler = make_router_and_handler()

    response = run_immediately(
        handler(
            farm_id=farm.id,
            request_body=EnvironmentalContextRequest(
                start_date=date(2020, 4, 1),
                end_date=date(2020, 4, 2),
                force_refresh=True,
            ),
            user=make_user(owner_id),
            farm_repository=InMemoryFarmRepository(farm),
            location_repository=InMemoryLocationRepository(),
            snapshot_service=snapshot_service,
        )
    )

    assert response.data_status == "unavailable"
    assert response.error_code == "NASA_TIMEOUT"
    assert all(indicator.value is None for indicator in response.indicators)
    assert snapshot_service.requests[0][1] is True


def test_environmental_storage_error_returns_safe_service_unavailable() -> None:
    farm = make_farm(PydanticObjectId(), PydanticObjectId())
    snapshot_service = InMemorySnapshotService(
        error=PyMongoError("mongodb://private-user:private-password@db.internal")
    )
    _, handler = make_router_and_handler()

    with pytest.raises(HTTPException) as unavailable:
        run_immediately(
            handler(
                farm_id=farm.id,
                request_body=EnvironmentalContextRequest(
                    start_date=date(2020, 4, 1),
                    end_date=date(2020, 4, 2),
                ),
                user=make_user(farm.owner_user_id),
                farm_repository=InMemoryFarmRepository(farm),
                location_repository=InMemoryLocationRepository(),
                snapshot_service=snapshot_service,
            )
        )

    assert unavailable.value.status_code == 503
    assert "private-user" not in unavailable.value.detail
    assert "private-password" not in unavailable.value.detail


def test_environmental_request_rejects_future_dates_and_invalid_ranges() -> None:
    tomorrow = date.today() + timedelta(days=1)
    with pytest.raises(ValueError, match="historical dates only"):
        EnvironmentalContextRequest(
            start_date=tomorrow,
            end_date=tomorrow,
        )
    with pytest.raises(ValueError, match="on or after"):
        EnvironmentalContextRequest(
            start_date=date(2020, 4, 2),
            end_date=date(2020, 4, 1),
        )


def test_rotation_historical_analysis_periods_must_be_past() -> None:
    today = date.today()
    with pytest.raises(ValueError, match="must be in the past"):
        make_rotation_request(
            historical_seasons=(
                {
                    "season_label": "one",
                    "analysis_start_date": today,
                    "analysis_end_date": today,
                },
                {
                    "season_label": "two",
                    "analysis_start_date": "2020-01-03",
                    "analysis_end_date": "2020-01-04",
                },
                {
                    "season_label": "three",
                    "analysis_start_date": "2020-01-05",
                    "analysis_end_date": "2020-01-06",
                },
            ),
        )


def test_rotation_recommendation_slots_must_be_future_periods() -> None:
    today = date.today()
    with pytest.raises(ValueError, match="must be in the future"):
        make_rotation_request(
            recommendation_seasons=(
                {"season_label": "one", "window_start": today, "window_end": today},
                {
                    "season_label": "two",
                    "window_start": today + timedelta(days=1),
                    "window_end": today + timedelta(days=2),
                },
                {
                    "season_label": "three",
                    "window_start": today + timedelta(days=3),
                    "window_end": today + timedelta(days=4),
                },
            )
        )


def test_rotation_workflow_uses_past_reports_and_returns_only_top_three_provisional_options() -> (
    None
):
    owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), owner_id)
    farm.farmer_priorities = PriorityPoints(
        water_resilience=50,
        soil_health_potential=20,
        yield_stability_proxy=20,
        labor_feasibility=10,
    )
    farm_repository = InMemoryFarmRepository(farm)
    snapshot_service = InMemorySnapshotService(
        retrieval_factory=lambda request: make_retrieval(request)
    )
    result_repository = InMemoryRotationResultRepository()
    router, _ = make_router_and_handler()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/farms/{farm_id}/rotation-recommendations"
    )
    request = make_rotation_request(
        historical_seasons=(
            {
                "season_label": "2020 major",
                "analysis_start_date": "2020-04-01",
                "analysis_end_date": "2020-04-02",
                "planted_crop": "maize",
            },
            {
                "season_label": "2020 minor",
                "analysis_start_date": "2020-09-01",
                "analysis_end_date": "2020-09-02",
                "planted_crop": "cowpea",
            },
            {
                "season_label": "2021 major",
                "analysis_start_date": "2021-04-01",
                "analysis_end_date": "2021-04-02",
                "planted_crop": "yam",
            },
        ),
    )

    response = run_immediately(
        route.endpoint(
            farm_id=farm.id,
            request_body=request,
            user=make_user(owner_id),
            farm_repository=farm_repository,
            location_repository=InMemoryLocationRepository(),
            snapshot_service=snapshot_service,
            result_repository=result_repository,
        )
    )
    body = response.model_dump(mode="json")
    saved_call = result_repository.create_calls[0]
    saved_result = saved_call["decision_inputs"]

    assert len(snapshot_service.requests) == 3
    assert [call[0].season_label for call in snapshot_service.requests] == [
        "2020 major",
        "2020 minor",
        "2021 major",
    ]
    assert [call[0].crop for call in snapshot_service.requests] == [
        "maize",
        "cowpea",
        "yam",
    ]
    future_slots = request.recommendation_seasons
    first_future_event = saved_call["candidate_generation"].candidates[0].events[0].event
    assert first_future_event.window_start == future_slots[0].window_start
    assert first_future_event.window_end == future_slots[0].window_end
    assert first_future_event.season_label == future_slots[0].season_label
    assert all(
        snapshot_request.start_date == season.analysis_start_date
        and snapshot_request.end_date == season.analysis_end_date
        for (snapshot_request, _force_refresh), season in zip(
            snapshot_service.requests,
            request.historical_seasons,
            strict=True,
        )
    )
    assert saved_call["owner_user_id"] == owner_id
    assert saved_call["decision_inputs"].scoring_request.farmer_priorities is None
    assert saved_call["decision_inputs"].generation_request.prior_crop_history == ("yam",)
    assert result_repository.saved_result is not None
    assert result_repository.saved_result.farm_inputs.farmer_priorities is None
    assert result_repository.saved_result is not None
    assert saved_result.generation_request.current_practice.crop_ids == (
        "maize",
        "cowpea",
        "yam",
    )
    assert saved_call["candidate_generation"].readiness == "needs_review"
    assert len(saved_call["candidate_generation"].candidates) == 216
    assert saved_call["scoring_result"].excluded_options == ()
    assert saved_call["scoring_result"].scoring_version == "ny8-scoring-v2"
    assert saved_call["scoring_result"].ranking_method == "lexicographic_water_then_optional_soil"
    assert saved_call["scoring_result"].ranking.status == "ranked"
    assert len(saved_call["scoring_result"].options) == 3
    assert all(
        criterion.criterion in {"water_resilience", "soil_health_potential"}
        for option in saved_call["scoring_result"].options
        for criterion in option.criteria
    )
    first_water_criterion = saved_call["scoring_result"].options[0].criteria[0]
    assert len(first_water_criterion.environmental_inputs) == 9
    assert all(item.data_status == "cached" for item in first_water_criterion.environmental_inputs)
    assert len(saved_result.environmental_snapshot_ids) == 3
    assert body["scoring_result"]["selected_weights"] is None
    assert body["scoring_result"]["default_weights"] is None
    assert len(body["scoring_result"]["options"]) == 3
    assert body["scoring_result"]["ranking"]["status"] == "ranked"
    assert body["crop_library_version"] == "ny8-crop-library-v1"
    assert body["assessment_version"] == "ny8-sequence-assessment-v1"
    assert body["rule_set_version"] == "ny8-rules-v1"
    assert len(body["environmental_snapshot_ids"]) == 3
    assert body["candidate_pool_summary"] == {
        "total_generated": 216,
        "total_excluded": 0,
        "total_needing_review": 216,
        "total_assessed": 125,
        "total_rankable": 124,
        "total_returned": 4,
    }
    assert "candidate_generation" not in body
    assert all(
        len(option["transition_assessments"]) == 3 for option in body["scoring_result"]["options"]
    )
    first_event = body["scoring_result"]["options"][0]["candidate"]["events"][0]["event"]
    assert first_event["plot_id"] == "plot-a"
    serialized = str(body).lower()
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "owner_user_id" not in serialized
    result_document_size = len(result_repository.saved_result.model_dump_json().encode("utf-8"))
    response_size = len(response.model_dump_json().encode("utf-8"))
    assert result_document_size < 16 * 1024 * 1024
    assert response_size < 8 * 1024 * 1024


def test_rotation_workflow_does_not_fetch_or_save_for_a_non_owned_farm() -> None:
    farm = make_farm(PydanticObjectId(), PydanticObjectId())
    snapshot_service = InMemorySnapshotService(
        retrieval_factory=lambda request: make_retrieval(request)
    )
    result_repository = InMemoryRotationResultRepository()
    router, _ = make_router_and_handler()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/farms/{farm_id}/rotation-recommendations"
    )
    request = make_rotation_request()

    with pytest.raises(HTTPException) as not_found:
        run_immediately(
            route.endpoint(
                farm_id=farm.id,
                request_body=request,
                user=make_user(PydanticObjectId()),
                farm_repository=InMemoryFarmRepository(farm),
                location_repository=InMemoryLocationRepository(),
                snapshot_service=snapshot_service,
                result_repository=result_repository,
            )
        )

    assert not_found.value.status_code == 404
    assert snapshot_service.requests == []
    assert result_repository.create_calls == []


def test_rotation_result_storage_error_returns_safe_service_unavailable() -> None:
    owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), owner_id)
    snapshot_service = InMemorySnapshotService(
        retrieval_factory=lambda request: make_retrieval(request)
    )
    result_repository = InMemoryRotationResultRepository(
        error=PyMongoError("mongodb://private-user:private-password@db.internal")
    )
    router, _ = make_router_and_handler()
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/farms/{farm_id}/rotation-recommendations"
    )
    request = make_rotation_request()

    with pytest.raises(HTTPException) as unavailable:
        run_immediately(
            route.endpoint(
                farm_id=farm.id,
                request_body=request,
                user=make_user(owner_id),
                farm_repository=InMemoryFarmRepository(farm),
                location_repository=InMemoryLocationRepository(),
                snapshot_service=snapshot_service,
                result_repository=result_repository,
            )
        )

    assert unavailable.value.status_code == 503
    assert "private-user" not in unavailable.value.detail
    assert "private-password" not in unavailable.value.detail
    assert len(snapshot_service.requests) == 3


def test_rotation_request_rejects_overlapping_periods_and_unknown_crop_ids() -> None:
    with pytest.raises(ValueError, match="chronological and non-overlapping"):
        make_rotation_request(
            historical_seasons=(
                {
                    "season_label": "one",
                    "analysis_start_date": "2020-01-01",
                    "analysis_end_date": "2020-01-10",
                },
                {
                    "season_label": "two",
                    "analysis_start_date": "2020-01-10",
                    "analysis_end_date": "2020-01-20",
                },
                {
                    "season_label": "three",
                    "analysis_start_date": "2020-02-01",
                    "analysis_end_date": "2020-02-10",
                },
            ),
        )
    with pytest.raises(ValueError, match="supported crop library"):
        make_rotation_request(
            historical_seasons=(
                {
                    "season_label": "one",
                    "analysis_start_date": "2020-01-01",
                    "analysis_end_date": "2020-01-02",
                    "planted_crop": "soybean",
                },
                {
                    "season_label": "two",
                    "analysis_start_date": "2020-01-03",
                    "analysis_end_date": "2020-01-04",
                },
                {
                    "season_label": "three",
                    "analysis_start_date": "2020-01-05",
                    "analysis_end_date": "2020-01-06",
                },
            ),
        )


def test_workflow_routes_require_the_app_specific_authenticated_user() -> None:
    def current_active_user() -> User:
        return make_user(PydanticObjectId())

    router = create_workflow_router(current_active_user)
    routes = [route for route in router.routes if isinstance(route, APIRoute)]

    assert {route.path for route in routes} == {
        "/farms/{farm_id}/environmental-context",
        "/farms/{farm_id}/rotation-recommendations",
    }
    assert all(route.methods == {"POST"} for route in routes)
    assert all(
        any(dependency.call is current_active_user for dependency in route.dependant.dependencies)
        for route in routes
    )
