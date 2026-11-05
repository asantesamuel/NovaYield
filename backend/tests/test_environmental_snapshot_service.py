"""Mock-backed tests for NY-6 cache, refresh, and fallback behavior."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from beanie import PydanticObjectId

from app.integrations.nasa.power import (
    NASA_POWER_DAILY_ENDPOINT,
    NASAPowerHttpClient,
    NASAPowerService,
    PowerHTTPError,
    PowerRequest,
    PowerResult,
    PowerTimeoutError,
    normalize_power_response,
)
from app.models.environmental_snapshots import (
    AutoRefreshRetry,
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


def make_http_payload(request: PowerRequest) -> dict[str, Any]:
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
                "PRECTOTCORR": {key: 2.0 for key in dates},
                "T2M": {key: 28.0 for key in dates},
                "T2M_MAX": {key: 34.0 for key in dates},
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


class FakeRepository:
    def __init__(self) -> None:
        self.snapshots: dict[str, EnvironmentalSnapshot] = {}
        self.insert_calls = 0
        self.replace_calls = 0
        self.lease_available = True
        self.lease_calls = 0
        self.release_calls = 0
        self.retry_marks = 0

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

    async def mark_auto_refresh_failure(
        self,
        identity: SnapshotIdentity,
        *,
        expected_retrieved_at: datetime,
        retry: AutoRefreshRetry,
    ) -> EnvironmentalSnapshot | None:
        self.retry_marks += 1
        snapshot = self.snapshots.get(identity.request_key)
        if snapshot is not None and snapshot.retrieved_at == expected_retrieved_at:
            snapshot = snapshot.model_copy(update={"auto_refresh_retry": retry})
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
    backoff: timedelta = timedelta(minutes=30),
) -> tuple[EnvironmentalSnapshotService, FakePowerService]:
    power_service = FakePowerService(power_results)
    service = EnvironmentalSnapshotService(
        repository=repository,
        nasa_service=power_service,  # type: ignore[arg-type]
        location_secret=LOCATION_SECRET,
        freshness_policy=policy,
        snapshot_factory=make_snapshot,
        auto_refresh_failure_backoff=backoff,
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


def test_read_only_cached_recovery_never_refreshes_even_when_stale() -> None:
    repository = FakeRepository()
    identity = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    snapshot = make_snapshot(identity, make_result(REQUEST, rain=3.0, retrieved_at=NOW))
    snapshot.id = PydanticObjectId()
    repository.snapshots[identity.request_key] = snapshot
    service, power = make_service(
        repository,
        [PowerTimeoutError("The provider must not be called")],
        policy=SnapshotFreshnessPolicy(refresh_after_by_source={"MERRA2": timedelta(days=1)}),
    )

    recovered = run_immediately(
        service.retrieve_cached(
            REQUEST,
            expected_snapshot_id=str(snapshot.id),
            now=NOW + timedelta(days=2),
        )
    )
    wrong_id = run_immediately(
        service.retrieve_cached(
            REQUEST,
            expected_snapshot_id=str(PydanticObjectId()),
            now=NOW + timedelta(days=2),
        )
    )

    assert recovered is not None
    assert recovered.snapshot is not None and recovered.snapshot.id == snapshot.id
    assert recovered.data_status == "cached"
    assert recovered.freshness.status == "stale"
    assert recovered.refresh_attempted is False
    assert wrong_id is None
    assert power.calls == 0
    assert repository.lease_calls == 0
    assert repository.replace_calls == 0


def test_nasa_http_adapter_flows_through_snapshot_cache_and_reuse() -> None:
    upstream_requests: list[httpx.Request] = []
    test_now = datetime.now(UTC)

    def mocked_nasa_response(request: httpx.Request) -> httpx.Response:
        upstream_requests.append(request)
        if len(upstream_requests) > 1:
            return httpx.Response(503, text="temporary outage near 77.123, 88.456")
        return httpx.Response(200, json=make_http_payload(REQUEST))

    async_http_client = httpx.AsyncClient(transport=httpx.MockTransport(mocked_nasa_response))
    nasa_service = NASAPowerService(NASAPowerHttpClient(async_http_client))
    repository = FakeRepository()
    cache_service = EnvironmentalSnapshotService(
        repository=repository,
        nasa_service=nasa_service,
        location_secret=LOCATION_SECRET,
        snapshot_factory=make_snapshot,
    )

    try:
        first = run_immediately(cache_service.retrieve(REQUEST, now=test_now))
        second = run_immediately(
            cache_service.retrieve(REQUEST, now=test_now + timedelta(minutes=1))
        )
        refreshed = run_immediately(
            cache_service.retrieve(
                REQUEST,
                force_refresh=True,
                now=test_now + timedelta(days=1),
            )
        )
    finally:
        run_immediately(async_http_client.aclose())

    assert len(upstream_requests) == 2
    assert str(upstream_requests[0].url).startswith(NASA_POWER_DAILY_ENDPOINT)
    assert upstream_requests[0].url.params["time-standard"] == "UTC"
    assert first.data_status == "live"
    assert first.snapshot is not None
    assert first.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 4.0
    assert first.snapshot.parameters["T2M"].metadata.source == "MERRA2"
    assert second.data_status == "cached"
    assert second.cache_action == "hit"
    assert second.snapshot is not None
    assert second.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 4.0
    assert refreshed.data_status == "cached"
    assert refreshed.cache_action == "refresh_failed"
    assert refreshed.error_code == PowerHTTPError.__name__
    assert refreshed.snapshot is not None
    assert refreshed.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value == 4.0
    assert "77.123" not in str(refreshed.warnings)


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


def test_recent_power_period_is_checked_once_after_documented_publication_lag() -> None:
    """A pre-publication retrieval is revisited without expiring old history."""

    request = PowerRequest(
        latitude=0.0,
        longitude=0.0,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 30),
    )
    first_time = datetime(2026, 10, 1, tzinfo=UTC)
    published_time = datetime(2026, 10, 3, tzinfo=UTC)
    repository = FakeRepository()
    service, power_service = make_service(
        repository,
        [
            make_result(request, rain=2.0, retrieved_at=first_time),
            make_result(request, rain=3.0, retrieved_at=published_time),
        ],
        policy=SnapshotFreshnessPolicy(recent_publication_lag=timedelta(days=3)),
    )

    first = run_immediately(service.retrieve(request, now=first_time))
    before_publication = run_immediately(
        service.retrieve(request, now=published_time - timedelta(days=1))
    )
    after_publication = run_immediately(service.retrieve(request, now=published_time))
    later = run_immediately(service.retrieve(request, now=published_time + timedelta(days=1)))

    assert first.cache_action == "miss"
    assert before_publication.cache_action == "hit"
    assert after_publication.cache_action == "refreshed"
    assert later.cache_action == "hit"
    assert power_service.calls == 2


def test_geos_it_period_checks_for_merra_replacement_and_keeps_cache_on_failure() -> None:
    """The source label, not a blanket historical TTL, triggers replacement checks."""

    request = PowerRequest(
        latitude=0.0,
        longitude=0.0,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 1),
    )
    first_time = datetime(2026, 7, 2, tzinfo=UTC)
    check_time = datetime(2026, 9, 1, tzinfo=UTC)
    repository = FakeRepository()
    first_result = make_result(request, rain=2.0, retrieved_at=first_time)
    first_result.provider_metadata.source_products = ["GEOS-IT"]
    for series in first_result.parameters.values():
        series.metadata.source = "GEOS-IT"
    policy = SnapshotFreshnessPolicy(
        geos_it_replacement_lag=timedelta(days=60),
        geos_it_recheck_interval=timedelta(days=30),
    )
    service, power_service = make_service(
        repository,
        [first_result, PowerTimeoutError("NASA POWER request timed out.")],
        policy=policy,
    )

    run_immediately(service.retrieve(request, now=first_time))
    result = run_immediately(service.retrieve(request, now=check_time))

    assert result.cache_action == "refresh_failed"
    assert result.data_status == "cached"
    assert result.freshness.status == "stale"
    assert result.snapshot is not None
    assert result.snapshot.provider_metadata.source_products == ["GEOS-IT"]
    assert power_service.calls == 2
    assert repository.retry_marks == 1
    assert result.snapshot.auto_refresh_retry.retry_after == check_time + timedelta(minutes=30)


def test_failed_geos_auto_refresh_defers_retries_across_service_instances_then_retries() -> None:
    request = PowerRequest(
        latitude=0.0,
        longitude=0.0,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 7, 1),
    )
    first_time = datetime(2026, 7, 2, tzinfo=UTC)
    check_time = datetime(2026, 9, 1, tzinfo=UTC)
    policy = SnapshotFreshnessPolicy(
        geos_it_replacement_lag=timedelta(days=60),
        geos_it_recheck_interval=timedelta(days=30),
    )
    repository = FakeRepository()
    geos_result = make_result(request, rain=2.0, retrieved_at=first_time)
    geos_result.provider_metadata.source_products = ["GEOS-IT"]
    for series in geos_result.parameters.values():
        series.metadata.source = "GEOS-IT"
    identity = build_snapshot_identity(request, location_secret=LOCATION_SECRET)
    repository.snapshots[identity.request_key] = make_snapshot(identity, geos_result)

    first_service, failed_power = make_service(
        repository,
        [PowerTimeoutError("NASA POWER request timed out.")],
        policy=policy,
        backoff=timedelta(minutes=45),
    )
    failed = run_immediately(first_service.retrieve(request, now=check_time))
    assert failed.cache_action == "refresh_failed"
    assert failed.data_status == "cached"
    assert failed_power.calls == 1
    assert repository.snapshots[identity.request_key].auto_refresh_retry.retry_after == (
        check_time + timedelta(minutes=45)
    )

    restarted_service, restarted_power = make_service(
        repository,
        [make_result(request, rain=4.0, retrieved_at=check_time + timedelta(minutes=46))],
        policy=policy,
        backoff=timedelta(minutes=45),
    )
    deferred = run_immediately(
        restarted_service.retrieve(request, now=check_time + timedelta(minutes=15))
    )
    assert deferred.cache_action == "refresh_deferred"
    assert deferred.freshness.status == "stale"
    assert deferred.refresh_attempted is False
    assert deferred.data_status == "cached"
    assert "2026-09-01T00:45:00+00:00" in deferred.warnings[0]
    assert restarted_power.calls == 0
    assert repository.lease_calls == 1  # the deferred request did not take a lease

    retried = run_immediately(
        restarted_service.retrieve(request, now=check_time + timedelta(minutes=46))
    )
    assert retried.cache_action == "refreshed"
    assert retried.snapshot.auto_refresh_retry is None
    assert retried.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value > (
        failed.snapshot.parameters["PRECTOTCORR"].seasonal_summary.value
    )
    assert restarted_power.calls == 1


def test_manual_force_refresh_bypasses_backoff_and_clears_marker_on_success() -> None:
    repository = FakeRepository()
    policy = SnapshotFreshnessPolicy({"MERRA2": timedelta(days=1)})
    service, power = make_service(
        repository,
        [
            make_result(REQUEST, rain=2.0, retrieved_at=NOW),
            PowerTimeoutError("NASA POWER request timed out."),
            make_result(REQUEST, rain=5.0, retrieved_at=NOW + timedelta(days=3)),
        ],
        policy=policy,
    )
    run_immediately(service.retrieve(REQUEST, now=NOW))
    failed = run_immediately(service.retrieve(REQUEST, now=NOW + timedelta(days=3)))
    assert failed.snapshot.auto_refresh_retry is not None
    assert power.calls == 2

    forced = run_immediately(
        service.retrieve(
            REQUEST,
            now=NOW + timedelta(days=3, minutes=1),
            force_refresh=True,
        )
    )
    assert forced.cache_action == "refreshed"
    assert forced.snapshot.auto_refresh_retry is None
    assert power.calls == 3


def test_manual_failure_does_not_create_or_extend_automatic_backoff() -> None:
    repository = FakeRepository()
    policy = SnapshotFreshnessPolicy({"MERRA2": timedelta(days=1)})
    service, power = make_service(
        repository,
        [
            make_result(REQUEST, rain=2.0, retrieved_at=NOW),
            PowerTimeoutError("NASA POWER request timed out."),
            make_result(REQUEST, rain=3.0, retrieved_at=NOW + timedelta(days=3)),
        ],
        policy=policy,
    )
    run_immediately(service.retrieve(REQUEST, now=NOW))
    manual_failed = run_immediately(
        service.retrieve(REQUEST, now=NOW + timedelta(days=3), force_refresh=True)
    )
    assert manual_failed.cache_action == "refresh_failed"
    assert manual_failed.snapshot.auto_refresh_retry is None
    assert repository.retry_marks == 0
    automatic = run_immediately(service.retrieve(REQUEST, now=NOW + timedelta(days=3)))
    assert automatic.cache_action == "refreshed"
    assert power.calls == 3


def test_mature_merra_history_is_reused_under_source_aware_policy() -> None:
    repository = FakeRepository()
    policy = SnapshotFreshnessPolicy(
        recent_publication_lag=timedelta(days=3),
        geos_it_replacement_lag=timedelta(days=60),
        geos_it_recheck_interval=timedelta(days=30),
    )
    service, power_service = make_service(
        repository,
        [make_result(REQUEST, rain=3.0, retrieved_at=NOW)],
        policy=policy,
    )

    run_immediately(service.retrieve(REQUEST, now=NOW))
    later = run_immediately(service.retrieve(REQUEST, now=NOW + timedelta(days=120)))

    assert later.cache_action == "hit"
    assert later.freshness.status == "unknown"
    assert power_service.calls == 1


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
