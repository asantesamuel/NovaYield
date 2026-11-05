"""Save-first Farm workflow that reuses NY-6's existing NASA snapshot service."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.farms.context_window import DerivedContextPeriod
from app.integrations.nasa.power import PowerRequest
from app.models.farms import Farm, FarmEnvironmentalContextState
from app.models.supported_locations import SupportedLocation
from app.repositories.environmental_snapshots import SnapshotRepositoryError
from app.repositories.farms import FarmRepository
from app.services.environmental_snapshots import EnvironmentalSnapshotService, SnapshotRetrieval


class FarmContextService:
    """Connect the saved Farm's derived period to one persisted snapshot ID."""

    async def refresh_after_save(
        self,
        *,
        farm: Farm,
        location: SupportedLocation,
        snapshot_service: EnvironmentalSnapshotService | None,
        farm_repository: FarmRepository,
        force_refresh: bool = False,
    ) -> Farm:
        """Never undo Farm creation/update when NASA is unavailable.

        The Farm is already durable before this runs. NY-6 alone decides cache
        identity, freshness, upstream refresh and provider failure behavior.
        """

        saved, _ = await self.retrieve_for_owned_farm(
            farm=farm,
            location=location,
            snapshot_service=snapshot_service,
            farm_repository=farm_repository,
            force_refresh=force_refresh,
        )
        return saved

    async def retrieve_for_owned_farm(
        self,
        *,
        farm: Farm,
        location: SupportedLocation,
        snapshot_service: EnvironmentalSnapshotService | None,
        farm_repository: FarmRepository,
        force_refresh: bool = False,
    ) -> tuple[Farm, SnapshotRetrieval | None]:
        """Return NY-6's exact outcome to NY-40 without a second NASA call."""

        current = farm.environmental_context
        if farm.id is None or current is None or current.period is None:
            return farm, None
        if farm.history_status != "complete":
            return farm, None
        period = current.period
        retrieval: SnapshotRetrieval | None = None
        power_request: PowerRequest | None = None
        if snapshot_service is None:
            context = _unavailable(period, "NASA_SERVICE_UNAVAILABLE")
        else:
            try:
                power_request = PowerRequest(
                    latitude=location.coordinates.latitude,
                    longitude=location.coordinates.longitude,
                    start_date=period.start_date,
                    end_date=period.end_date,
                )
                retrieval = await snapshot_service.retrieve(
                    power_request, force_refresh=force_refresh
                )
            except (ValidationError, ValueError):
                context = _unavailable(period, "CONTEXT_PERIOD_UNSUPPORTED")
            except (PyMongoError, SnapshotRepositoryError):
                context = _unavailable(period, "ENVIRONMENTAL_STORAGE_UNAVAILABLE")
            except Exception:
                # A provider/adapter can fail outside its typed service boundary.
                # Preserve the Farm and expose only a stable, non-secret code.
                context = _unavailable(period, "NASA_UNAVAILABLE")
            else:
                context = _context_from_retrieval(period, retrieval)

        try:
            saved = await farm_repository.set_environmental_context_by_owner(
                farm_id=farm.id,
                owner_user_id=farm.owner_user_id,
                expected_revision=farm.revision,
                context=context,
            )
        except (PyMongoError, SnapshotRepositoryError):
            # The Farm remains stored with its initial pending state. The user
            # can retry through the existing owned environmental-context route.
            return farm, None
        if saved is None:
            # A concurrent PATCH may have changed the input revision, or a
            # same-revision worker may have linked usable data before this
            # request's unavailable outcome. Never downgrade that link.
            try:
                latest = await farm_repository.get_by_owner(
                    farm_id=farm.id, owner_user_id=farm.owner_user_id
                )
            except PyMongoError:
                latest = None
            winning_context = latest.environmental_context if latest is not None else None
            if (
                latest is not None
                and latest.revision == farm.revision
                and latest.location_key == farm.location_key
                and winning_context is not None
                and winning_context.period == period
                and winning_context.status in {"ready", "partial"}
                and winning_context.snapshot_id is not None
                and snapshot_service is not None
                and power_request is not None
            ):
                winning_id = str(winning_context.snapshot_id)
                try:
                    cached = await snapshot_service.retrieve_cached(
                        power_request, expected_snapshot_id=winning_id
                    )
                except (PyMongoError, SnapshotRepositoryError, ValueError):
                    cached = None
                if cached is not None and cached.data_status != "unavailable":
                    return latest, cached
            return latest or farm, None
        return saved, retrieval


def _context_from_retrieval(
    period: DerivedContextPeriod, retrieval: SnapshotRetrieval
) -> FarmEnvironmentalContextState:
    snapshot = retrieval.snapshot
    if snapshot is None or snapshot.id is None or retrieval.data_status == "unavailable":
        return _unavailable(period, _safe_warning_code(retrieval.error_code))
    missing = any(
        series.seasonal_summary.coverage.missing_days > 0 for series in snapshot.parameters.values()
    )
    warning_code = None
    if retrieval.error_code is not None:
        warning_code = _safe_warning_code(retrieval.error_code)
    elif missing:
        warning_code = "NASA_PARTIAL_COVERAGE"
    return FarmEnvironmentalContextState(
        status="partial" if missing else "ready",
        period=period,
        snapshot_id=snapshot.id,
        data_status=retrieval.data_status,
        cache_action=retrieval.cache_action,
        warning_code=warning_code,
        updated_at=datetime.now(UTC),
    )


def _unavailable(period: DerivedContextPeriod, warning_code: str) -> FarmEnvironmentalContextState:
    return FarmEnvironmentalContextState(
        status="unavailable",
        period=period,
        data_status="unavailable",
        warning_code=warning_code,
        updated_at=datetime.now(UTC),
    )


_KNOWN_ERROR_CODES = {
    "PowerTimeoutError": "NASA_TIMEOUT",
    "PowerTransportError": "NASA_UNAVAILABLE",
    "PowerHTTPError": "NASA_UPSTREAM_ERROR",
    "PowerMalformedResponseError": "NASA_RESPONSE_INVALID",
    "PowerMissingParameterError": "NASA_RESPONSE_INVALID",
    "PowerUnsupportedUnitsError": "NASA_RESPONSE_INVALID",
    "SnapshotRefreshInProgress": "NASA_RETRIEVAL_IN_PROGRESS",
    "SnapshotRepositoryError": "ENVIRONMENTAL_STORAGE_UNAVAILABLE",
}


def _safe_warning_code(error_code: str | None) -> str:
    if error_code is None:
        return "NASA_NO_VALID_DATA"
    return _KNOWN_ERROR_CODES.get(error_code, "NASA_UNAVAILABLE")
