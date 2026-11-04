"""MongoDB farm profile document and owner lookup index (NY-19)."""

from datetime import UTC, datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.database.registry import register_document_model
from app.decisions.scoring import PriorityPoints
from app.farms.contracts import (
    FarmName,
    FarmText,
    LocationKey,
)

FARM_COLLECTION_NAME = "farms"
FARM_OWNER_INDEX_NAME = "ix_farms_owner_user_id"


@register_document_model
class Farm(Document):
    """One user's farm profile; ownership is an application-checked ObjectId."""

    owner_user_id: PydanticObjectId
    name: FarmName
    location_key: LocationKey
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[FarmText] | None = None
    current_practice: FarmText | None = None
    # Legacy persisted field: accepted when reading old farm documents, but
    # omitted from new farm API contracts and ignored by NY-8 v2.
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
