"""NASA POWER Daily Point client and normalized environmental response models.

The HTTP client is injected so callers can reuse one AsyncClient in the app
lifespan. This module never persists or logs request coordinates.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

NASA_POWER_DAILY_ENDPOINT = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_COMMUNITY = "AG"
NASA_POWER_PARAMETERS = ("PRECTOTCORR", "T2M", "T2M_MAX")
NASA_POWER_START_DATE = date(1981, 1, 1)
NASA_POWER_DEFAULT_TIMEOUT_SECONDS = 30.0

PowerParameterCode = Literal["PRECTOTCORR", "T2M", "T2M_MAX"]
CoverageStatus = Literal["complete", "partial", "unavailable"]


def create_nasa_power_http_client(
    *, timeout_seconds: float = NASA_POWER_DEFAULT_TIMEOUT_SECONDS
) -> httpx.AsyncClient:
    """Create the reusable HTTP client with an explicit upstream timeout.

    The application lifespan should create one instance and close it during
    shutdown. Tests can inject an in-memory client instead.
    """
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))


class PowerServiceError(Exception):
    """Base class for safe, typed NASA POWER service outcomes."""


class PowerTimeoutError(PowerServiceError):
    """The NASA POWER request exceeded its configured timeout."""


class PowerTransportError(PowerServiceError):
    """The request could not reach NASA POWER or the response could not be read."""


class PowerHTTPError(PowerServiceError):
    """NASA POWER returned a non-success HTTP status without exposing its body."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"NASA POWER returned HTTP {status_code}.")


class PowerMalformedResponseError(PowerServiceError):
    """NASA POWER returned data that does not match the expected response contract."""


class PowerMissingParameterError(PowerMalformedResponseError):
    """The response omitted a required parameter or its metadata."""

    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        super().__init__(f"NASA POWER response is missing required parameter {parameter}.")


class PowerUnsupportedUnitsError(PowerMalformedResponseError):
    """A requested parameter was returned in units this adapter cannot safely normalize."""

    def __init__(self, parameter: str, units: str) -> None:
        self.parameter = parameter
        self.units = units
        super().__init__(f"NASA POWER returned unsupported units for {parameter}: {units}.")


class PowerRequest(BaseModel):
    """Validated input for one point and inclusive UTC daily date window.

    Coordinates are required from an approved pilot/community point or an
    authorized farm record; this model deliberately has no default location.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    start_date: date
    end_date: date
    season_label: str | None = None
    calendar_source_version: str | None = None
    crop: str | None = None

    @model_validator(mode="after")
    def validate_date_window(self) -> PowerRequest:
        if self.start_date < NASA_POWER_START_DATE:
            raise ValueError("NASA POWER Daily data starts on 1981-01-01")
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        if self.end_date > datetime.now(UTC).date():
            raise ValueError("End date cannot be in the future")
        return self


class DateCoverage(BaseModel):
    """Per-parameter counts for the requested inclusive date interval."""

    requested_start_date: date
    requested_end_date: date
    returned_start_date: date | None
    returned_end_date: date | None
    expected_days: int = Field(ge=1)
    valid_days: int = Field(ge=0)
    missing_days: int = Field(ge=0)
    coverage_percent: float = Field(ge=0, le=100)


class DailyValue(BaseModel):
    """One UTC daily value; None means the source value was missing."""

    date: date
    value: float | None


class PowerParameterMetadata(BaseModel):
    """Provider metadata retained for one POWER parameter."""

    code: PowerParameterCode
    long_name: str
    source_units: str
    normalized_units: str
    source: str | None = None
    spatial_resolution: str | None = None
    fill_value: float


class SeasonalSummary(BaseModel):
    """Sum or mean over the selected request window, using valid days only."""

    method: Literal["sum", "mean"]
    value: float | None
    units: str
    status: CoverageStatus
    coverage: DateCoverage


class PowerParameterSeries(BaseModel):
    metadata: PowerParameterMetadata
    daily_values: list[DailyValue]
    seasonal_summary: SeasonalSummary


class PowerProviderMetadata(BaseModel):
    """Non-location provider metadata returned by NASA POWER."""

    api_name: str | None = None
    api_version: str | None = None
    header_title: str
    source_products: list[str] = Field(default_factory=list)
    spatial_resolution_note: str | None = None


class PowerDateWindow(BaseModel):
    """Requested dates and any caller-provided crop calendar context."""

    start_date: date
    end_date: date
    season_label: str | None = None
    calendar_source_version: str | None = None
    crop: str | None = None


class PowerResult(BaseModel):
    """Normalized, non-persisted response for one NASA POWER Daily Point query."""

    provider: Literal["NASA POWER"] = "NASA POWER"
    service: Literal["Daily Point"] = "Daily Point"
    retrieval_status: Literal["live"] = "live"
    source_url: str = NASA_POWER_DAILY_ENDPOINT
    community: Literal["AG"] = "AG"
    time_standard: Literal["UTC"] = "UTC"
    retrieved_at: datetime
    date_window: PowerDateWindow
    provider_metadata: PowerProviderMetadata
    parameters: dict[PowerParameterCode, PowerParameterSeries]
    warnings: list[str] = Field(default_factory=list)


class PowerClient(Protocol):
    """Interface that makes provider transport replaceable in tests or callers."""

    async def fetch_daily_point(self, request: PowerRequest) -> Mapping[str, Any]: ...


class NASAPowerHttpClient:
    """HTTP adapter for NASA POWER; the caller owns and closes the injected client."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def fetch_daily_point(self, request: PowerRequest) -> Mapping[str, Any]:
        """Retrieve JSON from NASA POWER with fixed MVP variables and UTC dates."""

        params = {
            "parameters": ",".join(NASA_POWER_PARAMETERS),
            "community": NASA_POWER_COMMUNITY,
            "latitude": request.latitude,
            "longitude": request.longitude,
            "start": request.start_date.strftime("%Y%m%d"),
            "end": request.end_date.strftime("%Y%m%d"),
            "format": "JSON",
            "units": "metric",
            "time-standard": "UTC",
        }
        try:
            response = await self._http_client.get(NASA_POWER_DAILY_ENDPOINT, params=params)
        except httpx.TimeoutException:
            raise PowerTimeoutError("NASA POWER request timed out.") from None
        except httpx.RequestError:
            raise PowerTransportError("NASA POWER request could not be completed.") from None

        if not 200 <= response.status_code < 300:
            raise PowerHTTPError(response.status_code)

        try:
            payload = response.json()
        except ValueError:
            raise PowerMalformedResponseError("NASA POWER returned invalid JSON.") from None

        if not isinstance(payload, Mapping):
            raise PowerMalformedResponseError("NASA POWER returned an unexpected JSON document.")
        return payload


class NASAPowerService:
    """Fetch, validate, and normalize NASA POWER data without caching or persistence."""

    def __init__(self, client: PowerClient) -> None:
        self._client = client

    async def retrieve(self, request: PowerRequest) -> PowerResult:
        """Return daily series and window summaries, preserving missingness and coverage."""

        payload = await self._client.fetch_daily_point(request)
        return normalize_power_response(payload, request)


def normalize_power_response(
    payload: Mapping[str, Any],
    request: PowerRequest,
    *,
    retrieved_at: datetime | None = None,
) -> PowerResult:
    """Validate the NASA JSON contract and calculate summaries over valid daily values."""

    if payload.get("type") != "Feature":
        raise PowerMalformedResponseError("NASA POWER response is not a point feature.")
    geometry = _require_mapping(payload.get("geometry"), "geometry")
    if geometry.get("type") != "Point":
        raise PowerMalformedResponseError("NASA POWER response geometry is not a point.")
    header = _require_mapping(payload.get("header"), "header")
    api = _require_mapping(header.get("api"), "header.api")
    messages = payload.get("messages")
    times = payload.get("times")
    if not isinstance(messages, list) or not isinstance(times, Mapping):
        raise PowerMalformedResponseError("NASA POWER response metadata is incomplete.")
    header_title = _require_text(header.get("title"), "header.title")
    api_name = _require_text(api.get("name"), "header.api.name")
    api_version = _require_text(api.get("version"), "header.api.version")
    fill_value = _require_number(header.get("fill_value"), "header.fill_value")
    provider_metadata = PowerProviderMetadata(
        api_name=api_name,
        api_version=api_version,
        header_title=header_title,
        source_products=_string_list(header.get("sources")),
        spatial_resolution_note=_optional_text(
            header.get("spatial_resolution") or header.get("resolution")
        )
        or (header_title if "resolution" in header_title.casefold() else None),
    )

    properties = _require_mapping(payload.get("properties"), "properties")
    parameter_data = _require_mapping(properties.get("parameter"), "properties.parameter")
    parameter_metadata = _require_mapping(payload.get("parameters"), "parameters")
    expected_days = (request.end_date - request.start_date).days + 1
    result_parameters: dict[PowerParameterCode, PowerParameterSeries] = {}
    warnings: list[str] = []

    for code in NASA_POWER_PARAMETERS:
        raw_values = parameter_data.get(code)
        if raw_values is None:
            raise PowerMissingParameterError(code)
        values_by_date = _require_mapping(raw_values, f"properties.parameter.{code}")

        raw_metadata = parameter_metadata.get(code)
        if raw_metadata is None:
            raise PowerMissingParameterError(code)
        metadata = _require_mapping(raw_metadata, f"parameters.{code}")
        long_name = _require_text(metadata.get("longname"), f"parameters.{code}.longname")
        source_units = _require_text(metadata.get("units"), f"parameters.{code}.units")
        normalized_units, summary_units, method = _normalized_units(code, source_units)
        parameter_fill_value = _require_number(
            metadata.get("fill_value", fill_value), f"parameters.{code}.fill_value"
        )
        source = _optional_text(metadata.get("source"))
        resolution = (
            _optional_text(metadata.get("resolution")) or provider_metadata.spatial_resolution_note
        )

        daily_values: list[DailyValue] = []
        valid_values: list[float] = []
        returned_dates: list[date] = []
        day = request.start_date
        while day <= request.end_date:
            key = day.strftime("%Y%m%d")
            if key in values_by_date:
                returned_dates.append(day)
                value = _daily_value(values_by_date[key], parameter_fill_value, code)
            else:
                value = None
            daily_values.append(DailyValue(date=day, value=value))
            if value is not None:
                valid_values.append(value)
            day += timedelta(days=1)

        valid_days = len(valid_values)
        missing_days = expected_days - valid_days
        coverage = DateCoverage(
            requested_start_date=request.start_date,
            requested_end_date=request.end_date,
            returned_start_date=min(returned_dates) if returned_dates else None,
            returned_end_date=max(returned_dates) if returned_dates else None,
            expected_days=expected_days,
            valid_days=valid_days,
            missing_days=missing_days,
            coverage_percent=round(valid_days / expected_days * 100, 2),
        )
        if valid_days == 0:
            summary_value = None
            status: CoverageStatus = "unavailable"
            warnings.append(f"{code} has no valid daily values in the requested date window.")
        else:
            summary_value = (
                math.fsum(valid_values) if method == "sum" else math.fsum(valid_values) / valid_days
            )
            status = "complete" if missing_days == 0 else "partial"
            if status == "partial":
                warnings.append(
                    f"{code} has partial coverage ({valid_days}/{expected_days} valid days); "
                    "the summary uses valid values only and does not fill missing days."
                )

        result_parameters[code] = PowerParameterSeries(
            metadata=PowerParameterMetadata(
                code=code,
                long_name=long_name,
                source_units=source_units,
                normalized_units=normalized_units,
                source=source,
                spatial_resolution=resolution,
                fill_value=parameter_fill_value,
            ),
            daily_values=daily_values,
            seasonal_summary=SeasonalSummary(
                method=method,
                value=summary_value,
                units=summary_units,
                status=status,
                coverage=coverage,
            ),
        )

    retrieval_time = retrieved_at or datetime.now(UTC)
    if retrieval_time.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")

    return PowerResult(
        retrieved_at=retrieval_time.astimezone(UTC),
        date_window=PowerDateWindow(
            start_date=request.start_date,
            end_date=request.end_date,
            season_label=request.season_label,
            calendar_source_version=request.calendar_source_version,
            crop=request.crop,
        ),
        provider_metadata=provider_metadata,
        parameters=result_parameters,
        warnings=warnings,
    )


def _normalized_units(code: str, source_units: str) -> tuple[str, str, Literal["sum", "mean"]]:
    normalized_source = source_units.strip().casefold().replace(" ", "")
    if code == "PRECTOTCORR" and normalized_source in {"mm/day", "mmday-1", "mm/d"}:
        return "mm/day", "mm/season", "sum"
    if code in {"T2M", "T2M_MAX"} and normalized_source in {"c", "°c", "degc"}:
        return "°C", "°C", "mean"
    raise PowerUnsupportedUnitsError(code, source_units)


def _daily_value(raw_value: Any, fill_value: float, parameter: str) -> float | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise PowerMalformedResponseError(
            f"NASA POWER returned a non-numeric daily value for {parameter}."
        )
    value = float(raw_value)
    if not math.isfinite(value):
        raise PowerMalformedResponseError(
            f"NASA POWER returned a non-finite daily value for {parameter}."
        )
    return None if value == fill_value else value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PowerMalformedResponseError(f"NASA POWER response field {field_name} is invalid.")
    return value


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PowerMalformedResponseError(f"NASA POWER response field {field_name} is invalid.")
    result = float(value)
    if not math.isfinite(result):
        raise PowerMalformedResponseError(f"NASA POWER response field {field_name} is invalid.")
    return result


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PowerMalformedResponseError(f"NASA POWER response field {field_name} is invalid.")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
