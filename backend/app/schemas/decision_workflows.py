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


class HistoricalSeasonReport(BaseModel):
    """A past farmer-reported season and its separate NASA analysis window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season_label: SeasonLabel
    analysis_start_date: date
    analysis_end_date: date
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
    def validate_historical_period(self) -> "HistoricalSeasonReport":
        """Ensure the NASA window is supported historical data, not a planting slot."""

        if self.analysis_start_date < NASA_POWER_START_DATE:
            raise ValueError("NASA POWER Daily data starts on 1981-01-01")
        if self.analysis_end_date < self.analysis_start_date:
            raise ValueError("Analysis end must be on or after its start")
        if self.analysis_end_date >= datetime.now(UTC).date():
            raise ValueError("Past-season analysis dates must be in the past")
        return self


class RecommendationSeasonSlot(BaseModel):
    """One future candidate slot; dates express intent, not a validated calendar."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season_label: SeasonLabel
    window_start: date
    window_end: date

    @model_validator(mode="after")
    def validate_future_window(self) -> "RecommendationSeasonSlot":
        """Require a future interval, while leaving crop/calendar suitability unknown."""

        if self.window_start <= datetime.now(UTC).date():
            raise ValueError("Recommendation season windows must be in the future")
        if self.window_end < self.window_start:
            raise ValueError("Recommendation season end must be on or after its start")
        return self


class RotationRecommendationRequest(BaseModel):
    """Separate reported history from future candidate slots; omit owner and coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plot_reference: PlotReference = Field(
        description="The farmer's own label for the one plot represented by all three seasons."
    )
    historical_seasons: tuple[HistoricalSeasonReport, ...] = Field(
        description=(
            "Three past farmer-reported seasons. Their date ranges are used only for NASA POWER "
            "analysis and their crops may supply the current-practice baseline."
        )
    )
    recommendation_seasons: tuple[RecommendationSeasonSlot, ...] = Field(
        description=(
            "Three future ordered planting slots for candidate generation. These are not NASA "
            "analysis windows and do not assert a reviewed crop calendar."
        )
    )
    force_refresh: bool = False

    @model_validator(mode="after")
    def validate_season_groups(self) -> "RotationRecommendationRequest":
        """Require three ordered historical reports and three separate future slots."""

        if len(self.historical_seasons) != 3:
            raise ValueError("Provide exactly three past farmer-reported seasons")
        if len(self.recommendation_seasons) != 3:
            raise ValueError("Provide exactly three future recommendation seasons")

        for previous, following in zip(
            self.historical_seasons,
            self.historical_seasons[1:],
            strict=False,
        ):
            if following.analysis_start_date <= previous.analysis_end_date:
                raise ValueError("Past analysis periods must be chronological and non-overlapping")

        for previous, following in zip(
            self.recommendation_seasons,
            self.recommendation_seasons[1:],
            strict=False,
        ):
            if following.window_start <= previous.window_end:
                raise ValueError(
                    "Future recommendation slots must be chronological and non-overlapping"
                )
        return self
