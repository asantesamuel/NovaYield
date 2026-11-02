"""HTTP tests for authenticated, farm-scoped rotation result reads."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from beanie import PydanticObjectId
from fastapi import HTTPException, status
from fastapi.routing import APIRoute

from app.decisions.rotation import (
    CropCandidate,
    PlantingEventSlot,
    RotationGenerationRequest,
    generate_rotation_candidates,
)
from app.decisions.scoring import (
    CRITERIA,
    CriterionEvidence,
    PriorityPoints,
    RotationOptionEvidence,
    ScoringRequest,
    score_rotation_options,
)
from app.indicators.environmental import EnvironmentalIndicator, IndicatorCoverage
from app.models.farms import Farm
from app.models.rotation_results import (
    ROTATION_RESULT_SCHEMA_VERSION,
    FarmDecisionInputSnapshot,
    RotationDecisionInputs,
    RotationResult,
)
from app.models.users import User
from app.rotation_results.routes import (
    FARM_NOT_FOUND_DETAIL,
    ROTATION_RESULT_NOT_FOUND_DETAIL,
    create_rotation_result_router,
)


def make_user(user_id: PydanticObjectId) -> User:
    """Create an authenticated-principal fixture without initializing Beanie."""

    return User.model_construct(id=user_id, email="farmer@example.com")


def make_farm(farm_id: PydanticObjectId, owner_user_id: PydanticObjectId) -> Farm:
    """Create a persisted-looking farm with no precise coordinates."""

    now = datetime(2026, 1, 2, tzinfo=UTC)
    return Farm.model_construct(
        id=farm_id,
        owner_user_id=owner_user_id,
        name="Test farm",
        location_key="ejura",
        soil_texture="unknown",
        irrigation_access=None,
        previous_crops=None,
        current_practice=None,
        farmer_priorities=PriorityPoints(
            water_resilience=25,
            soil_health_potential=25,
            yield_stability_proxy=25,
            labor_feasibility=25,
        ),
        created_at=now,
        updated_at=now,
    )


def make_result(
    *,
    result_id: PydanticObjectId,
    farm: Farm,
) -> RotationResult:
    """Build an NY-8 result with one cached indicator from a synthetic fixture."""

    generation_request = RotationGenerationRequest(
        planting_events=(
            PlantingEventSlot(
                event_id=f"event-{order}",
                order=order,
                plot_id="synthetic-test-plot",
                season_label=f"synthetic-season-{order}",
                window_start=date(2024, order, 1),
                window_end=date(2024, order, 10),
            )
            for order in (1, 2, 3)
        ),
        candidate_crops=(CropCandidate(crop_id="maize", display_name="Maize"),),
    )
    generated = generate_rotation_candidates(generation_request)
    indicator = EnvironmentalIndicator(
        code="seasonal_precipitation_total",
        name="Seasonal precipitation total",
        definition="Sum of valid daily precipitation values for the period.",
        calculation_method="sum",
        value=300.0,
        units="mm/season",
        status="complete",
        data_status="cached",
        source="NASA POWER",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        coverage=IndicatorCoverage(
            expected_days=91,
            valid_days=91,
            missing_days=0,
            coverage_percent=100,
        ),
        spatial_resolution="synthetic test grid",
    )
    evidence = tuple(
        CriterionEvidence(
            criterion=criterion,
            status="assessed",
            rating="moderate",
            confidence="low",
            rationale="Synthetic API fixture only; not an agronomic finding.",
            comparison_basis="synthetic-test-basis-v1",
            environmental_inputs=(indicator,) if criterion == "water_resilience" else (),
            evidence_references=("synthetic test fixture",),
            assumptions=("Synthetic fixture; never use as a recommendation.",),
        )
        for criterion in CRITERIA
    )
    scoring_request = ScoringRequest(
        options=(
            RotationOptionEvidence(
                candidate=generated.candidates[0],
                criteria=evidence,
                benefits=("Synthetic fixture benefit.",),
                trade_offs=("Synthetic fixture trade-off.",),
                assumptions=("Synthetic fixture only.",),
            ),
        )
    )
    return RotationResult.model_construct(
        id=result_id,
        schema_version=ROTATION_RESULT_SCHEMA_VERSION,
        owner_user_id=farm.owner_user_id,
        farm_id=farm.id,
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
        farm_inputs=FarmDecisionInputSnapshot.from_farm(farm),
        decision_inputs=RotationDecisionInputs(
            generation_request=generation_request,
            scoring_request=scoring_request,
        ),
        candidate_generation=generated,
        scoring_result=score_rotation_options(scoring_request),
    )


class InMemoryFarmRepository:
    """Apply the same owner constraint as the NY-19 farm repository."""

    def __init__(self, farms: list[Farm]) -> None:
        self.farms = {farm.id: farm for farm in farms}
        self.queries: list[dict[str, PydanticObjectId]] = []

    async def get_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
    ) -> Farm | None:
        self.queries.append({"farm_id": farm_id, "owner_user_id": owner_user_id})
        farm = self.farms.get(farm_id)
        if farm is None or farm.owner_user_id != owner_user_id:
            return None
        return farm


class InMemoryRotationResultRepository:
    """Filter fixtures with the same owner/farm/result dimensions as MongoDB."""

    def __init__(self, results: list[RotationResult]) -> None:
        self.results = results
        self.history_queries: list[dict[str, PydanticObjectId]] = []
        self.detail_queries: list[dict[str, PydanticObjectId]] = []

    async def list_by_owner_and_farm(
        self,
        *,
        owner_user_id: PydanticObjectId,
        farm_id: PydanticObjectId,
    ) -> list[RotationResult]:
        self.history_queries.append({"owner_user_id": owner_user_id, "farm_id": farm_id})
        return [
            result
            for result in self.results
            if result.owner_user_id == owner_user_id and result.farm_id == farm_id
        ]

    async def get_by_owner_farm_and_id(
        self,
        *,
        owner_user_id: PydanticObjectId,
        farm_id: PydanticObjectId,
        result_id: PydanticObjectId,
    ) -> RotationResult | None:
        self.detail_queries.append(
            {
                "owner_user_id": owner_user_id,
                "farm_id": farm_id,
                "result_id": result_id,
            }
        )
        return next(
            (
                result
                for result in self.results
                if result.owner_user_id == owner_user_id
                and result.farm_id == farm_id
                and result.id == result_id
            ),
            None,
        )


def make_router(
    *,
    user: User | None,
    farms: InMemoryFarmRepository,
    results: InMemoryRotationResultRepository,
) -> tuple[Any, Any]:
    """Build the feature router and expose its auth dependency for handler tests."""

    def current_active_user() -> User:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
            )
        return user

    return create_rotation_result_router(current_active_user), current_active_user


def get_route_endpoint(router: Any, path: str) -> Any:
    """Find a registered endpoint by its feature-relative route template."""

    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == path
    )


def run_immediately(awaitable: Any) -> Any:
    """Run a handler coroutine whose repository fakes never perform network I/O."""

    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("An in-memory route handler unexpectedly suspended.")


def test_owner_can_list_only_own_farm_results_with_safe_provenance() -> None:
    owner_id = PydanticObjectId()
    other_owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), owner_id)
    other_farm = make_farm(PydanticObjectId(), other_owner_id)
    own_result = make_result(result_id=PydanticObjectId(), farm=farm)
    other_result = make_result(result_id=PydanticObjectId(), farm=other_farm)
    farms = InMemoryFarmRepository([farm, other_farm])
    results = InMemoryRotationResultRepository([own_result, other_result])

    router, _ = make_router(user=make_user(owner_id), farms=farms, results=results)
    list_handler = get_route_endpoint(router, "/farms/{farm_id}/rotation-results")
    response = run_immediately(
        list_handler(
            farm_id=farm.id,
            user=make_user(owner_id),
            farm_repository=farms,
            result_repository=results,
        )
    )
    body = [item.model_dump(mode="json") for item in response]
    assert len(body) == 1
    assert body[0]["id"] == str(own_result.id)
    assert body[0]["farm_id"] == str(farm.id)
    assert set(body[0]) == {
        "id",
        "farm_id",
        "schema_version",
        "created_at",
        "farm_inputs",
        "generator_version",
        "scoring_result",
    }
    assert body[0]["generator_version"] == own_result.candidate_generation.generator_version
    rainfall = body[0]["scoring_result"]["options"][0]["criteria"][0]
    assert rainfall["environmental_inputs"][0]["source"] == "NASA POWER"
    assert rainfall["environmental_inputs"][0]["data_status"] == "cached"
    assert rainfall["environmental_inputs"][0]["period_start"] == "2024-01-01"
    assert rainfall["environmental_inputs"][0]["retrieved_at"] == "2026-01-01T00:00:00Z"
    serialized = str(body).lower()
    assert "owner_user_id" not in serialized
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized
    assert results.history_queries == [{"owner_user_id": owner_id, "farm_id": farm.id}]


def test_detail_hides_other_users_farm_or_result_ids() -> None:
    owner_id = PydanticObjectId()
    other_owner_id = PydanticObjectId()
    farm = make_farm(PydanticObjectId(), owner_id)
    other_farm = make_farm(PydanticObjectId(), other_owner_id)
    own_result = make_result(result_id=PydanticObjectId(), farm=farm)
    foreign_result = make_result(result_id=PydanticObjectId(), farm=other_farm)
    farms = InMemoryFarmRepository([farm, other_farm])
    results = InMemoryRotationResultRepository([own_result, foreign_result])

    router, _ = make_router(user=make_user(owner_id), farms=farms, results=results)
    detail_handler = get_route_endpoint(
        router,
        "/farms/{farm_id}/rotation-results/{result_id}",
    )
    own = run_immediately(
        detail_handler(
            farm_id=farm.id,
            result_id=own_result.id,
            user=make_user(owner_id),
            farm_repository=farms,
            result_repository=results,
        )
    )
    missing_result_id = PydanticObjectId()

    with pytest.raises(HTTPException) as changed_farm:
        run_immediately(
            detail_handler(
                farm_id=other_farm.id,
                result_id=own_result.id,
                user=make_user(owner_id),
                farm_repository=farms,
                result_repository=results,
            )
        )
    with pytest.raises(HTTPException) as changed_result:
        run_immediately(
            detail_handler(
                farm_id=farm.id,
                result_id=foreign_result.id,
                user=make_user(owner_id),
                farm_repository=farms,
                result_repository=results,
            )
        )
    with pytest.raises(HTTPException) as missing_result:
        run_immediately(
            detail_handler(
                farm_id=farm.id,
                result_id=missing_result_id,
                user=make_user(owner_id),
                farm_repository=farms,
                result_repository=results,
            )
        )

    assert own.id == str(own_result.id)
    assert changed_farm.value.status_code == 404
    assert changed_farm.value.detail == FARM_NOT_FOUND_DETAIL
    assert changed_result.value.status_code == missing_result.value.status_code == 404
    assert changed_result.value.detail == missing_result.value.detail
    assert changed_result.value.detail == ROTATION_RESULT_NOT_FOUND_DETAIL
    assert results.detail_queries == [
        {
            "owner_user_id": owner_id,
            "farm_id": farm.id,
            "result_id": own_result.id,
        },
        {
            "owner_user_id": owner_id,
            "farm_id": farm.id,
            "result_id": foreign_result.id,
        },
        {
            "owner_user_id": owner_id,
            "farm_id": farm.id,
            "result_id": missing_result_id,
        },
    ]


def test_history_and_detail_routes_require_an_authenticated_user() -> None:
    results = InMemoryRotationResultRepository([])
    farms = InMemoryFarmRepository([])

    router, current_active_user = make_router(user=None, farms=farms, results=results)
    routes = [route for route in router.routes if isinstance(route, APIRoute)]

    assert {route.path for route in routes} == {
        "/farms/{farm_id}/rotation-results",
        "/farms/{farm_id}/rotation-results/{result_id}",
    }
    assert all(route.methods == {"GET"} for route in routes)
    assert all(
        any(dependency.call is current_active_user for dependency in route.dependant.dependencies)
        for route in routes
    )
    with pytest.raises(HTTPException) as anonymous:
        current_active_user()

    assert anonymous.value.status_code == 401
    assert farms.queries == []
    assert results.history_queries == []
    assert results.detail_queries == []
