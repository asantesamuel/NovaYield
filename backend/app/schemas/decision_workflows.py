"""Public HTTP contracts for the saved-farm environmental and rotation flow.

Farm history is entered once through NY-39. Recommendation callers identify the
owned farm and may adjust priorities; they never supply NASA or future dates.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.decisions.scoring import PriorityPoints
from app.indicators.environmental import EnvironmentalIndicator
from app.schemas.farms import FarmLocationSummary
from app.services.environmental_snapshots import CacheAction, DataStatus, FreshnessStatus


class EnvironmentalContextRequest(BaseModel):
    """An optional explicit refresh of the context period already saved on a farm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    force_refresh: bool = False


class EnvironmentalPeriodResponse(BaseModel):
    """The exact inclusive historical range derived from saved crop events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date
    policy_version: str = "ny38-calendar-month-v1"


class EnvironmentalContextResponse(BaseModel):
    """Owner-safe context status, indicators, and provenance without coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    farm_id: str
    location: FarmLocationSummary
    period: EnvironmentalPeriodResponse
    context_status: Literal["pending", "ready", "partial", "unavailable"]
    snapshot_id: str | None = None
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


class RotationRecommendationRequest(BaseModel):
    """The owner may override saved priority points for this one generation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    priority_adjustment: PriorityPoints | None = Field(
        default=None,
        description=(
            "Optional four-criterion priority points for this result. When omitted, "
            "the farm's saved priorities are used."
        ),
    )
