"""Farm profile value types and defaults shared across NY-19 layers."""

import re
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.decisions.scoring import PriorityPoints

FarmName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
FarmText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
CropName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_PRECISE_COORDINATE_TEXT = re.compile(r"(?<!\w)[+-]?\d{1,3}\.\d{3,}(?!\w)")

DEFAULT_FARMER_PRIORITIES: dict[str, int] = {
    "water_resilience": 25,
    "soil_health_potential": 25,
    "yield_stability_proxy": 25,
    "labor_feasibility": 25,
}


def default_farmer_priorities() -> PriorityPoints:
    """Create the approved equal-priority starting values for a new farm."""

    return PriorityPoints(**DEFAULT_FARMER_PRIORITIES)


def validate_location_label(value: str) -> str:
    """Reject coordinate-like numbers before a place label can be returned."""

    if _PRECISE_COORDINATE_TEXT.search(value):
        raise ValueError("Location label cannot contain precise coordinate values")
    return value


class FarmLocationData(BaseModel):
    """Location persisted for later environmental workflows.

    Precise coordinates stay in this private data object and are intentionally
    omitted by the public farm response schema.
    """

    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("label")
    @classmethod
    def reject_coordinate_text(cls, value: str) -> str:
        """Keep free-form place labels from echoing precise coordinates publicly."""

        return validate_location_label(value)

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> "FarmLocationData":
        """Accept a precise point only when both coordinates are supplied."""

        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together")
        return self
