"""Farm save-first linkage to the existing snapshot boundary, including race safety."""

import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any

from beanie import PydanticObjectId

from app.farms.context_window import DerivedContextPeriod
from app.farms.contracts import LocationCoordinates
from app.farms.environmental_context import FarmContextService
from app.models.farms import Farm, FarmEnvironmentalContextState
from app.models.supported_locations import SupportedLocation
from app.services.environmental_snapshots import FreshnessAssessment, SnapshotRetrieval


def _farm() -> Farm:
    return Farm.model_construct(
        id=PydanticObjectId(),
        owner_user_id=PydanticObjectId(),
        schema_version="farm-v2",
        revision=3,
        name="Synthetic plot",
        location_key="ejura",
        history_status="complete",
        environmental_context=FarmEnvironmentalContextState(
            status="pending",
            period=DerivedContextPeriod(
                start_date=date(2023, 7, 15),
                end_date=date(2024, 7, 15),
                history_start=date(2024, 3, 15),
                history_end=date(2024, 7, 15),
            ),
        ),
    )


def _location() -> SupportedLocation:
    return SupportedLocation.model_construct(
        location_key="ejura",
        label="Ejura",
        coordinates=LocationCoordinates(latitude=7.3856, longitude=-1.3562),
    )


class FakeSnapshotService:
    def __init__(
        self,
        result: SnapshotRetrieval | Exception,
        *,
        cached_result: SnapshotRetrieval | None = None,
    ) -> None:
        self.result = result
        self.cached_result = cached_result
        self.requests: list[Any] = []
        self.cache_reads: list[tuple[Any, str]] = []

    async def retrieve(self, request: Any, *, force_refresh: bool) -> SnapshotRetrieval:
        self.requests.append((request, force_refresh))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def retrieve_cached(
        self, request: Any, *, expected_snapshot_id: str
    ) -> SnapshotRetrieval | None:
        self.cache_reads.append((request, expected_snapshot_id))
        return self.cached_result


class FakeFarmRepository:
    def __init__(
        self,
        farm: Farm,
        *,
        race: bool = False,
        winning_context: FarmEnvironmentalContextState | None = None,
    ) -> None:
        self.farm = farm
        self.race = race
        self.winning_context = winning_context
        self.updates: list[tuple[Any, ...]] = []

    async def set_environmental_context_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        expected_revision: int,
        context: FarmEnvironmentalContextState,
    ) -> Farm | None:
        self.updates.append((farm_id, owner_user_id, expected_revision, context))
        if self.winning_context is not None and context.status == "unavailable":
            # Another worker won with usable data for this exact revision.
            self.farm = self.farm.model_copy(update={"environmental_context": self.winning_context})
            return None
        if self.race or expected_revision != self.farm.revision:
            return None
        self.farm = self.farm.model_copy(update={"environmental_context": context})
        return self.farm

    async def get_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
    ) -> Farm | None:
        if farm_id == self.farm.id and owner_user_id == self.farm.owner_user_id:
            return self.farm
        return None


def _retrieval(*, missing_days: int = 0) -> SnapshotRetrieval:
    coverage = SimpleNamespace(missing_days=missing_days)
    series = SimpleNamespace(seasonal_summary=SimpleNamespace(coverage=coverage))
    snapshot = SimpleNamespace(id=PydanticObjectId(), parameters={"PRECTOTCORR": series})
    return SnapshotRetrieval(
        snapshot=snapshot,
        data_status="live",
        cache_action="miss",
        freshness=FreshnessAssessment("fresh", 0, "Retrieved now"),
        refresh_attempted=True,
    )


def test_save_first_service_links_only_snapshot_id_and_returns_same_retrieval() -> None:
    farm = _farm()
    result = _retrieval()
    service = FakeSnapshotService(result)
    repository = FakeFarmRepository(farm)

    saved, returned = asyncio.run(
        FarmContextService().retrieve_for_owned_farm(
            farm=farm,
            location=_location(),
            snapshot_service=service,
            farm_repository=repository,
        )
    )

    assert returned is result
    assert len(service.requests) == 1
    assert service.requests[0][0].start_date == date(2023, 7, 15)
    assert service.requests[0][0].end_date == date(2024, 7, 15)
    assert saved.environmental_context.status == "ready"
    assert saved.environmental_context.snapshot_id == result.snapshot.id
    assert repository.updates[0][2] == 3
    assert "parameters" not in saved.environmental_context.model_dump()


def test_partial_and_upstream_failure_keep_honest_state_on_saved_farm() -> None:
    partial_farm = _farm()
    partial_repo = FakeFarmRepository(partial_farm)
    partial, _ = asyncio.run(
        FarmContextService().retrieve_for_owned_farm(
            farm=partial_farm,
            location=_location(),
            snapshot_service=FakeSnapshotService(_retrieval(missing_days=2)),
            farm_repository=partial_repo,
        )
    )
    assert partial.environmental_context.status == "partial"
    assert partial.environmental_context.warning_code == "NASA_PARTIAL_COVERAGE"

    failed_farm = _farm()
    failed_repo = FakeFarmRepository(failed_farm)
    failed, retrieval = asyncio.run(
        FarmContextService().retrieve_for_owned_farm(
            farm=failed_farm,
            location=_location(),
            snapshot_service=FakeSnapshotService(
                TimeoutError("provider timeout with secret=https://private.example")
            ),
            farm_repository=failed_repo,
        )
    )
    assert retrieval is None
    assert failed.environmental_context.status == "unavailable"
    assert failed.environmental_context.warning_code == "NASA_UNAVAILABLE"
    assert "private.example" not in str(failed.environmental_context.model_dump())


def test_concurrent_history_patch_discards_old_nasa_retrieval() -> None:
    farm = _farm()
    repository = FakeFarmRepository(farm, race=True)
    result = _retrieval()
    saved, returned = asyncio.run(
        FarmContextService().retrieve_for_owned_farm(
            farm=farm,
            location=_location(),
            snapshot_service=FakeSnapshotService(result),
            farm_repository=repository,
        )
    )
    assert returned is None
    assert saved.environmental_context.status == "pending"
    assert repository.updates[0][2] == farm.revision


def test_same_revision_worker_failure_keeps_winning_snapshot_and_reads_cache() -> None:
    farm = _farm()
    period = farm.environmental_context.period
    winner = _retrieval()
    assert period is not None and winner.snapshot is not None
    winning_context = FarmEnvironmentalContextState(
        status="ready",
        period=period,
        snapshot_id=winner.snapshot.id,
        data_status="live",
    )
    repository = FakeFarmRepository(farm, winning_context=winning_context)
    unavailable = SnapshotRetrieval(
        snapshot=None,
        data_status="unavailable",
        cache_action="refresh_in_progress",
        freshness=FreshnessAssessment("unknown", None, "Another worker owns the request lease."),
        refresh_attempted=False,
        error_code="SnapshotRefreshInProgress",
    )
    cached_winner = SnapshotRetrieval(
        snapshot=winner.snapshot,
        data_status="cached",
        cache_action="hit",
        freshness=winner.freshness,
        refresh_attempted=False,
    )
    snapshots = FakeSnapshotService(unavailable, cached_result=cached_winner)

    saved, returned = asyncio.run(
        FarmContextService().retrieve_for_owned_farm(
            farm=farm,
            location=_location(),
            snapshot_service=snapshots,
            farm_repository=repository,
        )
    )

    assert saved.revision == farm.revision
    assert saved.environmental_context == winning_context
    assert returned is cached_winner
    assert len(snapshots.requests) == 1
    assert len(snapshots.cache_reads) == 1
    assert snapshots.cache_reads[0][1] == str(winner.snapshot.id)
    assert repository.updates[0][3].status == "unavailable"
