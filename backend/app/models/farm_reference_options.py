"""Backend-owned, versioned broad farmer input choices; no measured field claims."""

from datetime import UTC, datetime
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.database.registry import register_document_model
from app.farms.contracts import CropKey, FarmText

REFERENCE_SCHEMA_VERSION = "farm-reference-v1"
ReferenceKind = Literal["soil_texture", "irrigation_access"]


@register_document_model
class FarmReferenceOption(Document):
    """A stable key and honest definition for one selectable farm input."""

    schema_version: str = REFERENCE_SCHEMA_VERSION
    kind: ReferenceKind
    key: CropKey
    label: FarmText
    definition: FarmText
    source_url: str | None = None
    source_status: Literal["product_taxonomy", "sourced_definition"] = "product_taxonomy"
    selectable: bool = True
    version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "farm_reference_options"
        indexes = [
            IndexModel(
                [("kind", ASCENDING), ("key", ASCENDING)],
                unique=True,
                name="uq_farm_reference_kind_key",
            ),
            IndexModel(
                [("kind", ASCENDING), ("selectable", ASCENDING), ("key", ASCENDING)],
                name="ix_farm_reference_selectable",
            ),
        ]
