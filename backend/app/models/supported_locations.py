"""Curated supported places with private NASA POWER query coordinates."""

from datetime import UTC, datetime
from typing import Literal

from beanie import Document
from pydantic import AnyHttpUrl, Field
from pymongo import ASCENDING, IndexModel

from app.database.registry import register_document_model
from app.farms.contracts import FarmText, LocationCoordinates, LocationKey

SUPPORTED_LOCATION_COLLECTION_NAME = "supported_locations"
SUPPORTED_LOCATION_KEY_INDEX_NAME = "uq_supported_locations_key"
SUPPORTED_LOCATION_ORDER_INDEX_NAME = "ix_supported_locations_selectable_order"


@register_document_model
class SupportedLocation(Document):
    """One selectable town/community reference point and its provenance."""

    location_key: LocationKey
    label: FarmText
    locality: FarmText
    administrative_area: FarmText
    region: FarmText
    country: FarmText = "Ghana"
    coordinates: LocationCoordinates
    point_scope: Literal["inhabited_place_reference"]
    coordinate_source: FarmText
    coordinate_source_url: AnyHttpUrl
    validation_status: Literal["provisional", "reviewed"] = "provisional"
    is_selectable: bool = True
    sort_order: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = SUPPORTED_LOCATION_COLLECTION_NAME
        indexes = [
            IndexModel(
                [("location_key", ASCENDING)],
                unique=True,
                name=SUPPORTED_LOCATION_KEY_INDEX_NAME,
            ),
            IndexModel(
                [
                    ("is_selectable", ASCENDING),
                    ("sort_order", ASCENDING),
                    ("location_key", ASCENDING),
                ],
                name=SUPPORTED_LOCATION_ORDER_INDEX_NAME,
            ),
        ]
