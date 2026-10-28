"""Mock-backed tests for NY-6 cache, refresh, and fallback behavior."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.integrations.nasa.power import (
    PowerRequest,
    PowerResult,
    PowerTimeoutError,
    normalize_power_response,
)
from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotIdentity,
    SnapshotSeasonContext,
    build_snapshot_identity,
    snapshot_fields_from_power_result,
)
from app.repositories.environmental_snapshots import SnapshotInsertOutcome
from app.services.environmental_snapshots import (
    EnvironmentalSnapshotService,
    SnapshotFreshnessPolicy,
    SnapshotRetrieval,
)

LOCATION_SECRET = "service-tests-only-location-key-with-more-than-32-bytes"
REQUEST = PowerRequest(
    latitude=0.0,
    longitude=0.0,
    start_date=date(2024, 1, 1),
    end_date=date(2024, 1, 2),
    season_label="major-season-v1",
    calendar_source_version="research-v1",
    crop="maize",
)
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def run_immediately(awaitable: Any) -> Any:
    """Run service coroutines backed only by immediate in-memory fakes."""
    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("The in-memory service fake unexpectedly suspended.")


def make_result(request: PowerRequest, *, rain: float, retrieved_at: datetime) -> PowerResult:
    dates = []
    current = request.start_date
    while current <= request.end_date:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    parameter_values = {
        "PRECTOTCORR": {key: rain for key in dates},
        "T2M": {key: 28.0 for key in dates},
        "T2M_MAX": {key: 34.0 for key in dates},
    }
    payload = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {"parameter": parameter_values},
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
    return normalize_power_response(payload, request, retrieved_at=retrieved_at)


def make_snapshot(identity: SnapshotIdentity, result: PowerResult) -> EnvironmentalSnapshot:
    return EnvironmentalSnapshot.model_construct(
        **snapshot_fields_from_power_result(identity, result)
    )


class FakeRepository:
    def __init__(self) -> None:
        self.snapshots: dict[str, EnvironmentalSnapshot] = {}
        self.insert_calls = 0
        self.replace_calls = 0
        self.lease_available = True
        self.lease_calls = 0
        self.release_calls = 0

    async def find_by_identity(self, identity: SnapshotIdentity) -> EnvironmentalSnapshot | None:
        return self.snapshots.get(identity.request_key)

    async def insert_if_absent(self, snapshot: EnvironmentalSnapshot) -> SnapshotInsertOutcome:
        self.insert_calls += 1
        existing = self.snapshots.get(snapshot.identity.request_key)
        if existing is not None:
            return SnapshotInsertOutcome(snapshot=existing, inserted=False)
        self.snapshots[snapshot.identity.request_key] = snapshot
        return SnapshotInsertOutcome(snapshot=snapshot, inserted=True)

    async def replace_after_refresh(self, snapshot: EnvironmentalSnapshot) -> SnapshotInsertOutcome:
        self.replace_calls += 1
        previous = self.snapshots.get(snapshot.identity.request_key)
        if previous is None:
            return await self.insert_if_absent(snapshot)
        refreshed_contexts = list(snapshot.request_contexts)
        snapshot.request_contexts = list(previous.request_contexts)
        for context in refreshed_contexts:
            if context not in snapshot.request_contexts:
                snapshot.request_contexts.append(context)
        self.snapshots[snapshot.identity.request_key] = snapshot
        return SnapshotInsertOutcome(snapshot=snapshot, inserted=False, replaced=True)

    async def add_request_context(
        self, identity: SnapshotIdentity, context: SnapshotSeasonContext
    ) -> EnvironmentalSnapshot | None:
        snapshot = self.snapshots.get(identity.request_key)
        if snapshot is None:
            return None
        contexts = list(snapshot.request_contexts)
        if context not in contexts:
            contexts.append(context)
            snapshot = snapshot.model_copy(update={"request_contexts": contexts})
            self.snapshots[identity.request_key] = snapshot
        return snapshot

    async def try_acquire_request_lease(
        self,
        _request_key: str,
        *,
        owner_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool:
        self.lease_calls += 1
        assert owner_token
        assert expires_at > now
        return self.lease_available

    async def release_request_lease(self, _request_key: str, *, owner_token: str) -> None:
        self.release_calls += 1
        assert owner_token


class FakePowerService:
    def __init__(self, results: list[PowerResult | Exception]) -> None:
        self.results = list(results)
        self.calls = 0

    async def retrieve(self, _request: PowerRequest) -> PowerResult:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_service(
    repository: FakeRepository,
    power_results: list[PowerResult | Exception],
    *,
    policy: SnapshotFreshnessPolicy | None = None,
) -> tuple[EnvironmentalSnapshotService, FakePowerService]:
    power_service = FakePowerService(power_results)
    service = EnvironmentalSnapshotService(
        repository=repository,
        nasa_service=power_service,  # type: ignore[arg-type]
        location_secret=LOCATION_SECRET,
        freshness_policy=policy,
        snapshot_factory=make_snapshot,
    )
    return service, power_service


def test_cache_miss_persists_live_values_and_later_hit_skips_nasa() -> None:
    repository = FakeRepository()
    service, power_service = make_service(
        repository,
        [make_result(REQUEST, rain=3.0, retrieved_at=NOW)],
    )

    first = run_immediately(service.retrieve(REQUEST, now=NOW))
    second = run_immediately(service.retrieve(REQUEST, now=NOW + timedelta(minutes=1)))

    assert isinstance(first, SnapshotRetrieval)
    assert first.data_status == "live"
    assert first.cache_action == "miss"
    assert first.snapshot is not None
    assert first.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 6.0
    assert second.data_status == "cached"
    assert second.cache_action == "hit"
    assert second.freshness.status == "unknown"
    assert second.snapshot is not None
    assert second.snapshot.request_contexts == [
        SnapshotSeasonContext(
            season_label="major-season-v1",
            calendar_source_version="research-v1",
            crop="maize",
        )
    ]
    assert power_service.calls == 1
    assert repository.insert_calls == 1
    assert repository.lease_calls == 1
    assert repository.release_calls == 1


def test_source_policy_refreshes_stale_snapshot_and_replaces_it() -> None:
    repository = FakeRepository()
    policy = SnapshotFreshnessPolicy({"MERRA2": timedelta(days=1)})
    identity = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    repository.snapshots[identity.request_key] = make_snapshot(
        identity, make_result(REQUEST, rain=2.0, retrieved_at=NOW - timedelta(days=3))
    )
    service, power_service = make_service(
        repository, [make_result(REQUEST, rain=4.0, retrieved_at=NOW)], policy=policy
    )

    refreshed = run_immediately(service.retrieve(REQUEST, now=NOW))

    assert refreshed.data_status == "live"
    assert refreshed.cache_action == "refreshed"
    assert refreshed.freshness.status == "fresh"
    assert refreshed.snapshot is not None
    assert refreshed.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 8.0
    assert repository.replace_calls == 1
    assert power_service.calls == 1


def test_unknown_policy_reuses_cached_data_until_explicit_refresh() -> None:
    repository = FakeRepository()
    service, power_service = make_service(
        repository,
        [
            make_result(REQUEST, rain=2.0, retrieved_at=NOW),
            make_result(REQUEST, rain=5.0, retrieved_at=NOW + timedelta(days=10)),
        ],
    )

    run_immediately(service.retrieve(REQUEST, now=NOW))
    automatic = run_immediately(service.retrieve(REQUEST, now=NOW + timedelta(days=10)))
    explicit = run_immediately(
        service.retrieve(REQUEST, now=NOW + timedelta(days=10), force_refresh=True)
    )

    assert automatic.data_status == "cached"
    assert automatic.freshness.status == "unknown"
    assert automatic.refresh_attempted is False
    assert explicit.data_status == "live"
    assert explicit.cache_action == "refreshed"
    assert explicit.snapshot is not None
    assert explicit.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 10.0
    assert power_service.calls == 2


def test_refresh_failure_preserves_and_labels_last_cached_snapshot() -> None:
    repository = FakeRepository()
    policy = SnapshotFreshnessPolicy({"MERRA2": timedelta(days=1)})
    service, power_service = make_service(
        repository,
        [
            make_result(REQUEST, rain=3.0, retrieved_at=NOW),
            PowerTimeoutError("NASA POWER request timed out."),
        ],
        policy=policy,
    )

    run_immediately(service.retrieve(REQUEST, now=NOW))
    failed_refresh = run_immediately(
        service.retrieve(REQUEST, now=NOW + timedelta(days=3), force_refresh=True)
    )

    assert failed_refresh.data_status == "cached"
    assert failed_refresh.cache_action == "refresh_failed"
    assert failed_refresh.refresh_attempted is True
    assert failed_refresh.error_code == "PowerTimeoutError"
    assert "cached data" in failed_refresh.warnings[0]
    assert failed_refresh.snapshot is not None
    assert failed_refresh.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 6.0
    assert repository.replace_calls == 0
    assert power_service.calls == 2


def test_refresh_failure_without_snapshot_returns_unavailable_without_fallback() -> None:
    repository = FakeRepository()
    service, power_service = make_service(
        repository,
        [PowerTimeoutError("NASA POWER request timed out.")],
    )

    unavailable = run_immediately(service.retrieve(REQUEST, now=NOW))

    assert unavailable.data_status == "unavailable"
    assert unavailable.cache_action == "unavailable"
    assert unavailable.snapshot is None
    assert unavailable.error_code == "PowerTimeoutError"
    assert repository.snapshots == {}
    assert power_service.calls == 1


def test_active_request_lease_prevents_a_second_upstream_call() -> None:
    repository = FakeRepository()
    repository.lease_available = False
    service, power_service = make_service(
        repository, [make_result(REQUEST, rain=2.0, retrieved_at=NOW)]
    )

    result = run_immediately(service.retrieve(REQUEST, now=NOW))

    assert result.data_status == "unavailable"
    assert result.cache_action == "refresh_in_progress"
    assert result.error_code == "SnapshotRefreshInProgress"
    assert power_service.calls == 0
    assert repository.release_calls == 0


def test_active_refresh_lease_serves_stored_snapshot_as_stale_cached_data() -> None:
    repository = FakeRepository()
    repository.lease_available = False
    policy = SnapshotFreshnessPolicy({"MERRA2": timedelta(days=1)})
    identity = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    repository.snapshots[identity.request_key] = make_snapshot(
        identity, make_result(REQUEST, rain=3.0, retrieved_at=NOW - timedelta(days=3))
    )
    service, power_service = make_service(repository, [], policy=policy)

    result = run_immediately(service.retrieve(REQUEST, now=NOW))

    assert result.data_status == "cached"
    assert result.cache_action == "refresh_in_progress"
    assert result.refresh_attempted is False
    assert result.freshness.status == "stale"
    assert result.snapshot is not None
    assert result.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 6.0
    assert power_service.calls == 0
    assert repository.release_calls == 0


def test_expired_known_source_triggers_refresh_even_if_another_source_is_missing() -> None:
    result = make_result(REQUEST, rain=2.0, retrieved_at=NOW)
    assert result.parameters["T2M"].metadata.source == "MERRA2"
    incomplete = result.model_copy(
        update={
            "parameters": {
                **result.parameters,
                "T2M": result.parameters["T2M"].model_copy(
                    update={
                        "metadata": result.parameters["T2M"].metadata.model_copy(
                            update={"source": None}
                        )
                    }
                ),
            }
        }
    )
    identity = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    snapshot = make_snapshot(identity, incomplete)

    freshness = SnapshotFreshnessPolicy({"MERRA2": timedelta(days=1)}).assess(
        snapshot, now=NOW + timedelta(days=10)
    )

    assert freshness.status == "stale"
    assert freshness.age_seconds == timedelta(days=10).total_seconds()
