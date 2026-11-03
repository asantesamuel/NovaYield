"""HTTP contracts for authenticated environmental and rotation workflows."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.decisions.rotation import CropId
from app.indicators.environmental import EnvironmentalIndicator
from app.integrations.nasa.power import NASA_POWER_START_DATE
from app.schemas.farms import FarmLocationSummary
from app.services.environmental_snapshots import CacheAction, DataStatus, FreshnessStatus

SeasonLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9 _-]+$",
    ),
]
PlotReference = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class EnvironmentalContextRequest(BaseModel):
    """Select a past NASA POWER period for an authenticated farm's catalog point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date
    force_refresh: bool = False

    @model_validator(mode="after")
    def validate_period(self) -> "EnvironmentalContextRequest":
        """Reject unsupported and future ranges before any database or NASA work."""

        if self.start_date < NASA_POWER_START_DATE:
            raise ValueError("NASA POWER Daily data starts on 1981-01-01")
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")
        if self.end_date > datetime.now(UTC).date():
            raise ValueError("Environmental context supports historical dates only")
        return self


class EnvironmentalPeriodResponse(BaseModel):
    """The exact inclusive historical date range used by the request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date


class EnvironmentalContextResponse(BaseModel):
    """Safe, traceable farm context with no owner ID or coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    farm_id: str
    location: FarmLocationSummary
    period: EnvironmentalPeriodResponse
    data_status: DataStatus
    cache_action: CacheAction
    freshness_status: FreshnessStatus
    freshness_age_seconds: float | None
    freshness_explanation: str
    refresh_attempted: bool
    error_code: (
        Literal[
            "NASA_TIMEOUT",
            "NASA_UNAVAILABLE",
            "NASA_UPSTREAM_ERROR",
            "NASA_RESPONSE_INVALID",
            "NASA_RETRIEVAL_IN_PROGRESS",
            "ENVIRONMENTAL_STORAGE_UNAVAILABLE",
            "NO_VALID_DATA",
        ]
        | None
    ) = None
    indicators: tuple[EnvironmentalIndicator, ...]
    warnings: tuple[str, ...] = ()


class ReportedPlantingSeason(BaseModel):
    """One farmer-reported historical planting period used as a NASA query window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season_label: SeasonLabel
    window_start: date
    window_end: date
    planted_crop: CropId | None = None

    @field_validator("planted_crop")
    @classmethod
    def require_approved_crop(cls, value: CropId | None) -> CropId | None:
        """Limit reported crop IDs to the agreed initial candidate library."""

        approved = {"maize", "cowpea", "groundnut", "cassava", "yam", "rice"}
        if value is not None and value not in approved:
            raise ValueError("Select a crop from NovaYield's supported crop library")
        return value

    @model_validator(mode="after")
    def validate_historical_period(self) -> "ReportedPlantingSeason":
        """Ensure each report can be used by the historical NASA POWER service."""

        if self.window_start < NASA_POWER_START_DATE:
            raise ValueError("NASA POWER Daily data starts on 1981-01-01")
        if self.window_end < self.window_start:
            raise ValueError("Season end must be on or after its start")
        if self.window_end >= datetime.now(UTC).date():
            raise ValueError("Reported planting seasons must be in the past")
        return self


class RotationRecommendationRequest(BaseModel):
    """Submit three past seasons for the same plot; never submit owner or coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plot_reference: PlotReference = Field(
        description="The farmer's own label for the one plot represented by all three seasons."
    )
    planting_seasons: tuple[ReportedPlantingSeason, ...]
    force_refresh: bool = False

    @model_validator(mode="after")
    def validate_three_chronological_seasons(self) -> "RotationRecommendationRequest":
        """Require exactly three chronological, non-overlapping historical periods."""

        if len(self.planting_seasons) != 3:
            raise ValueError("Provide exactly three past planting seasons for one plot")
        for previous, following in zip(
            self.planting_seasons,
            self.planting_seasons[1:],
            strict=False,
        ):
            if following.window_start <= previous.window_end:
                raise ValueError("Planting seasons must be chronological and non-overlapping")
        return self
