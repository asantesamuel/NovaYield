"""Owner-scoped Farm v2 history and context reference, with v1 read compatibility."""

from datetime import UTC, date, datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ASCENDING, IndexModel

from app.database.registry import register_document_model
from app.decisions.scoring import PriorityPoints
from app.farms.context_window import DerivedContextPeriod
from app.farms.contracts import (
    CropKey,
    FarmName,
    FarmText,
    LocationKey,
)

FARM_COLLECTION_NAME = "farms"
FARM_OWNER_INDEX_NAME = "ix_farms_owner_user_id"
FARM_V1_SCHEMA_VERSION = "farm-v1"
FARM_V2_SCHEMA_VERSION = "farm-v2"
HistoryStatus = Literal["complete", "needs_review", "unknown", "legacy_unresolved"]
ContextStatus = Literal["pending", "ready", "partial", "unavailable", "needs_review"]


class CropHistoryEvent(BaseModel):
    """One farmer-reported crop event on this Farm's single decision plot."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    crop_id: PydanticObjectId
    crop_key_snapshot: CropKey
    sequence_order: int = Field(ge=1, le=3)
    start_date: date | None = None
    end_date: date | None = None
    variety_key: CropKey | None = None
    production_system_key: CropKey | None = None
    date_precision: Literal["day", "unknown"] = "day"
    date_source: Literal["farmer_reported"] = "farmer_reported"


class HistoryGap(BaseModel):
    """An explicit report between crops; absence is not inferred fallow."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    status: Literal["fallow", "idle_unknown_management", "unknown"]
    source: Literal["farmer_reported", "extension_verified"] = "farmer_reported"
    reviewer_ref: str | None = None
    reviewed_at: datetime | None = None


class FarmEnvironmentalContextState(BaseModel):
    """Small reference/status envelope; the daily NASA series stays in NY-6."""

    model_config = ConfigDict(extra="forbid")

    status: ContextStatus
    period: DerivedContextPeriod | None = None
    snapshot_id: PydanticObjectId | None = None
    data_status: Literal["live", "cached", "unavailable"] | None = None
    cache_action: str | None = None
    warning_code: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@register_document_model
class Farm(Document):
    """One user's farm profile; ownership is an application-checked ObjectId."""

    owner_user_id: PydanticObjectId
    # Missing v2 fields on an old Mongo record deliberately parse as unresolved
    # v1; no free-text crop/date migration is inferred by Pydantic defaults.
    schema_version: str = FARM_V1_SCHEMA_VERSION
    revision: int = Field(default=0, ge=0)
    name: FarmName
    location_key: LocationKey
    soil_texture_key: CropKey | None = None
    soil_texture_source: Literal["farmer_reported", "measured", "unknown"] = "unknown"
    irrigation_access_key: CropKey | None = None
    history_status: HistoryStatus = "legacy_unresolved"
    crop_history: list[CropHistoryEvent] = Field(default_factory=list)
    declared_gaps: list[HistoryGap] = Field(default_factory=list)
    current_plot_available: bool | None = None
    earliest_available_date: date | None = None
    environmental_context: FarmEnvironmentalContextState | None = None
    # v1 fields remain readable internally, but cannot supply authoritative
    # v2 crop IDs, event chronology, field measurements, or a baseline.
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[FarmText] | None = None
    current_practice: FarmText | None = None
    # Farmer-entered relative priority points used by the NY-8 four-criterion ranking.
    farmer_priorities: PriorityPoints | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = FARM_COLLECTION_NAME
        indexes = [
            IndexModel(
                [("owner_user_id", ASCENDING)],
                name=FARM_OWNER_INDEX_NAME,
            )
        ]
