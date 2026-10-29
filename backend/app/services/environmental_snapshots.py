"""NASA POWER snapshot reuse and refresh orchestration (NY-6)."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.integrations.nasa.power import (
    NASA_POWER_DEFAULT_TIMEOUT_SECONDS,
    NASAPowerService,
    PowerRequest,
    PowerResult,
    PowerServiceError,
)
from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotIdentity,
    SnapshotSeasonContext,
    build_snapshot_identity,
)
from app.repositories.environmental_snapshots import (
    EnvironmentalSnapshotRepository,
    SnapshotInsertOutcome,
    SnapshotRepositoryError,
)

FreshnessStatus = Literal["fresh", "stale", "unknown"]
DataStatus = Literal["live", "cached", "unavailable"]
CacheAction = Literal[
    "miss", "hit", "refreshed", "refresh_failed", "refresh_in_progress", "unavailable"
]


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    status: FreshnessStatus
    age_seconds: float | None
    reason: str


class SnapshotFreshnessPolicy:
    """Optional source-specific age rules; no implicit TTL is supplied.

    If a parameter's source has no configured rule, its freshness is unknown.
    Unknown snapshots are reused with their age visible until explicitly
    refreshed or a source rule is configured.
    """

    def __init__(self, refresh_after_by_source: Mapping[str, timedelta] | None = None) -> None:
        normalized: dict[str, timedelta] = {}
        for source, interval in (refresh_after_by_source or {}).items():
            if not source.strip() or interval <= timedelta(0):
                raise ValueError("Source refresh rules need a name and a positive interval")
            normalized[source.strip().casefold()] = interval
        self._refresh_after_by_source = normalized

    def assess(
        self, snapshot: EnvironmentalSnapshot | None, *, now: datetime
    ) -> FreshnessAssessment:
        if snapshot is None:
            return FreshnessAssessment("unknown", None, "No stored snapshot exists.")

        current_time = _as_utc(now)
        retrieved_at = _as_utc(snapshot.retrieved_at)
        age_seconds = max(0.0, (current_time - retrieved_at).total_seconds())
        if not self._refresh_after_by_source:
            return FreshnessAssessment(
                "unknown", age_seconds, "No source refresh interval is configured."
            )

        parameter_sources = [series.metadata.source for series in snapshot.parameters.values()]
        if not parameter_sources:
            return FreshnessAssessment(
                "unknown", age_seconds, "A required parameter has no source metadata."
            )

        known_sources = [source for source in parameter_sources if source]
        if not known_sources:
            return FreshnessAssessment(
                "unknown", age_seconds, "A required parameter has no source metadata."
            )

        missing_rules = [
            source
            for source in known_sources
            if source.strip().casefold() not in self._refresh_after_by_source
        ]
        stale_sources = sorted(
            {
                source.strip()
                for source in known_sources
                if source.strip().casefold() in self._refresh_after_by_source
                and age_seconds
                >= self._refresh_after_by_source[source.strip().casefold()].total_seconds()
            }
        )
        if stale_sources:
            return FreshnessAssessment(
                "stale",
                age_seconds,
                f"Configured refresh interval elapsed for source(s): {', '.join(stale_sources)}.",
            )
        if missing_rules or len(known_sources) != len(parameter_sources):
            return FreshnessAssessment(
                "unknown",
                age_seconds,
                "No refresh interval is configured for every parameter source.",
            )
        return FreshnessAssessment(
            "fresh", age_seconds, "All parameter sources are within configured intervals."
        )


@dataclass(frozen=True, slots=True)
class SnapshotRetrieval:
    """Service result that keeps cached/live/unavailable provenance explicit."""

    snapshot: EnvironmentalSnapshot | None
    data_status: DataStatus
    cache_action: CacheAction
    freshness: FreshnessAssessment
    refresh_attempted: bool
    error_code: str | None = None
    warnings: tuple[str, ...] = ()


class SnapshotRepository(Protocol):
    async def find_by_identity(
        self, identity: SnapshotIdentity
    ) -> EnvironmentalSnapshot | None: ...

    async def insert_if_absent(self, snapshot: EnvironmentalSnapshot) -> SnapshotInsertOutcome: ...

    async def replace_after_refresh(
        self, snapshot: EnvironmentalSnapshot
    ) -> SnapshotInsertOutcome: ...

    async def add_request_context(
        self, identity: SnapshotIdentity, context: SnapshotSeasonContext
    ) -> EnvironmentalSnapshot | None: ...

    async def try_acquire_request_lease(
        self,
        request_key: str,
        *,
        owner_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool: ...

    async def release_request_lease(self, request_key: str, *, owner_token: str) -> None: ...


SnapshotFactory = Callable[[SnapshotIdentity, PowerResult], EnvironmentalSnapshot]


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class _RequestLockPool:
    """Coalesce equal requests within one application process."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._entries: dict[str, _LockEntry] = {}

    @asynccontextmanager
    async def hold(self, request_key: str) -> AsyncIterator[None]:
        async with self._guard:
            entry = self._entries.setdefault(request_key, _LockEntry())
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.users -= 1
                if entry.users == 0:
                    self._entries.pop(request_key, None)


class EnvironmentalSnapshotService:
    """Reuse stored NASA values and refresh only when policy or caller requests it."""

    def __init__(
        self,
        *,
        repository: SnapshotRepository | None = None,
        nasa_service: NASAPowerService,
        location_secret: str | bytes,
        freshness_policy: SnapshotFreshnessPolicy | None = None,
        snapshot_factory: SnapshotFactory = EnvironmentalSnapshot.from_power_result,
        request_lease_seconds: float = NASA_POWER_DEFAULT_TIMEOUT_SECONDS + 30.0,
    ) -> None:
        if request_lease_seconds <= NASA_POWER_DEFAULT_TIMEOUT_SECONDS:
            raise ValueError(
                "Request lease must outlast NASA POWER's configured 30-second client timeout"
            )
        self._repository = repository or EnvironmentalSnapshotRepository()
        self._nasa_service = nasa_service
        self._location_secret = location_secret
        self._freshness_policy = freshness_policy or SnapshotFreshnessPolicy()
        self._snapshot_factory = snapshot_factory
        self._request_lease_duration = timedelta(seconds=request_lease_seconds)
        self._request_locks = _RequestLockPool()

    async def retrieve(
        self,
        request: PowerRequest,
        *,
        force_refresh: bool = False,
        now: datetime | None = None,
    ) -> SnapshotRetrieval:
        """Return a cache hit or fetch and persist a fresh normalized response."""

        requested_at = _as_utc(now or datetime.now(UTC))
        identity = build_snapshot_identity(request, location_secret=self._location_secret)

        async with self._request_locks.hold(identity.request_key):
            stored = await self._repository.find_by_identity(identity)
            assessment = self._freshness_policy.assess(stored, now=requested_at)

            # A concurrent explicit refresh that completed while this caller waited
            # satisfies this caller's refresh request too.
            refreshed_while_waiting = (
                force_refresh and stored is not None and _as_utc(stored.retrieved_at) > requested_at
            )
            should_refresh = (
                stored is None
                or assessment.status == "stale"
                or (force_refresh and not refreshed_while_waiting)
            )
            if not should_refresh:
                return await self._serve_cached(identity, request, stored, assessment)

            lease_token = secrets.token_urlsafe(24)
            try:
                acquired = await self._repository.try_acquire_request_lease(
                    identity.request_key,
                    owner_token=lease_token,
                    now=requested_at,
                    expires_at=requested_at + self._request_lease_duration,
                )
            except SnapshotRepositoryError as error:
                if stored is not None:
                    return self._result_for(
                        stored,
                        request,
                        data_status=_status_for_snapshot(stored, cached=True),
                        cache_action="refresh_failed",
                        freshness=assessment,
                        refresh_attempted=False,
                        error_code=type(error).__name__,
                        warnings=(
                            "Refresh was skipped because request coordination is unavailable; "
                            "the stored snapshot is returned.",
                        ),
                    )
                return SnapshotRetrieval(
                    snapshot=None,
                    data_status="unavailable",
                    cache_action="unavailable",
                    freshness=FreshnessAssessment(
                        "unknown", None, "No persisted snapshot is available."
                    ),
                    refresh_attempted=False,
                    error_code=type(error).__name__,
                    warnings=("NASA retrieval was skipped because request coordination failed.",),
                )

            if not acquired:
                latest = await self._repository.find_by_identity(identity)
                if latest is not None:
                    latest_assessment = self._freshness_policy.assess(latest, now=requested_at)
                    return await self._serve_cached(
                        identity,
                        request,
                        latest,
                        latest_assessment,
                        cache_action="refresh_in_progress",
                        warnings=(
                            "Another request is refreshing this snapshot; "
                            "the stored copy is returned.",
                        ),
                    )
                return SnapshotRetrieval(
                    snapshot=None,
                    data_status="unavailable",
                    cache_action="refresh_in_progress",
                    freshness=FreshnessAssessment(
                        "unknown", None, "Another request is retrieving this identity."
                    ),
                    refresh_attempted=False,
                    error_code="SnapshotRefreshInProgress",
                    warnings=(
                        "Another request is retrieving this data. Retry after it completes.",
                    ),
                )

            try:
                return await self._refresh_and_persist(identity, request, stored, assessment)
            finally:
                try:
                    await self._repository.release_request_lease(
                        identity.request_key, owner_token=lease_token
                    )
                except SnapshotRepositoryError:
                    # The lease expires automatically if MongoDB cannot release it.
                    pass

    async def _refresh_and_persist(
        self,
        identity: SnapshotIdentity,
        request: PowerRequest,
        stored: EnvironmentalSnapshot | None,
        assessment: FreshnessAssessment,
    ) -> SnapshotRetrieval:
        try:
            power_result = await self._nasa_service.retrieve(request)
        except PowerServiceError as error:
            return await self._refresh_failed(identity, request, stored, assessment, error)

        snapshot = self._snapshot_factory(identity, power_result)
        try:
            if stored is None:
                outcome = await self._repository.insert_if_absent(snapshot)
            else:
                outcome = await self._repository.replace_after_refresh(snapshot)
        except SnapshotRepositoryError as error:
            if stored is not None:
                return self._result_for(
                    stored,
                    request,
                    data_status=_status_for_snapshot(stored, cached=True),
                    cache_action="refresh_failed",
                    freshness=assessment,
                    refresh_attempted=True,
                    error_code=type(error).__name__,
                    warnings=(
                        "The fresh NASA response could not be stored; the previous snapshot "
                        "is returned.",
                    ),
                )
            return SnapshotRetrieval(
                snapshot=None,
                data_status="unavailable",
                cache_action="unavailable",
                freshness=FreshnessAssessment(
                    "unknown", None, "No persisted snapshot is available."
                ),
                refresh_attempted=True,
                error_code=type(error).__name__,
                warnings=("NASA data was retrieved but could not be persisted.",),
            )

        if outcome.inserted or outcome.replaced:
            return SnapshotRetrieval(
                snapshot=outcome.snapshot,
                data_status=_status_for_snapshot(outcome.snapshot, cached=False),
                cache_action="miss" if stored is None else "refreshed",
                freshness=FreshnessAssessment("fresh", 0.0, "NASA POWER was just retrieved."),
                refresh_attempted=True,
            )

        # Another process inserted this identity while this request was fetching.
        raced_snapshot = outcome.snapshot
        raced_assessment = self._freshness_policy.assess(raced_snapshot, now=datetime.now(UTC))
        return await self._serve_cached(
            identity,
            request,
            raced_snapshot,
            raced_assessment,
            warnings=("A matching snapshot was stored by another request.",),
        )

    async def _serve_cached(
        self,
        identity: SnapshotIdentity,
        request: PowerRequest,
        snapshot: EnvironmentalSnapshot,
        assessment: FreshnessAssessment,
        *,
        cache_action: CacheAction = "hit",
        warnings: tuple[str, ...] = (),
    ) -> SnapshotRetrieval:
        context = _request_context(request)
        try:
            snapshot = await self._repository.add_request_context(identity, context) or snapshot
        except SnapshotRepositoryError:
            warnings += ("The current season context could not be recorded in MongoDB.",)
        return self._result_for(
            snapshot,
            request,
            data_status=_status_for_snapshot(snapshot, cached=True),
            cache_action=cache_action,
            freshness=assessment,
            refresh_attempted=False,
            warnings=warnings,
        )

    async def _refresh_failed(
        self,
        identity: SnapshotIdentity,
        request: PowerRequest,
        snapshot: EnvironmentalSnapshot | None,
        assessment: FreshnessAssessment,
        error: PowerServiceError,
    ) -> SnapshotRetrieval:
        if snapshot is None:
            return SnapshotRetrieval(
                snapshot=None,
                data_status="unavailable",
                cache_action="unavailable",
                freshness=FreshnessAssessment(
                    "unknown", None, "No persisted snapshot is available."
                ),
                refresh_attempted=True,
                error_code=type(error).__name__,
                warnings=(str(error),),
            )

        try:
            current = await self._repository.add_request_context(
                identity, _request_context(request)
            )
            fallback = current or snapshot
        except SnapshotRepositoryError:
            fallback = snapshot
        warning = (
            f"NASA POWER refresh failed; serving the last stored snapshot as cached data. {error}"
        )
        return self._result_for(
            fallback,
            request,
            data_status=_status_for_snapshot(fallback, cached=True),
            cache_action="refresh_failed",
            freshness=assessment,
            refresh_attempted=True,
            error_code=type(error).__name__,
            warnings=(warning,),
        )

    def _result_for(
        self,
        snapshot: EnvironmentalSnapshot,
        request: PowerRequest,
        *,
        data_status: DataStatus,
        cache_action: CacheAction,
        freshness: FreshnessAssessment,
        refresh_attempted: bool,
        error_code: str | None = None,
        warnings: tuple[str, ...] = (),
    ) -> SnapshotRetrieval:
        # Context belongs to this use of the shared environmental series. It is
        # carried by the result so a cached snapshot's original crop cannot replace it.
        contexts = list(snapshot.request_contexts)
        context = _request_context(request)
        if context not in contexts:
            contexts.append(context)
        result_snapshot = snapshot.model_copy(update={"request_contexts": contexts})
        return SnapshotRetrieval(
            snapshot=result_snapshot,
            data_status=data_status,
            cache_action=cache_action,
            freshness=freshness,
            refresh_attempted=refresh_attempted,
            error_code=error_code,
            warnings=warnings,
        )


def _request_context(request: PowerRequest) -> SnapshotSeasonContext:
    return SnapshotSeasonContext(
        season_label=request.season_label,
        calendar_source_version=request.calendar_source_version,
        crop=request.crop,
    )


def _status_for_snapshot(snapshot: EnvironmentalSnapshot, *, cached: bool) -> DataStatus:
    has_valid_data = any(
        series.seasonal_summary.coverage.valid_days > 0 for series in snapshot.parameters.values()
    )
    if not has_valid_data:
        return "unavailable"
    return "cached" if cached else "live"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        # PyMongo returns BSON UTC datetimes as naive values unless tz_aware is enabled.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
