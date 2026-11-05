"""Farm profile value types and equal-weight preference defaults shared across NY-19 layers."""

from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints

from app.decisions.scoring import PriorityPoints

FarmName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
FarmText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
CropName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CropKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$",
    ),
]
LocationKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]

# Default preference points used when a farmer has not selected priorities.
DEFAULT_FARMER_PRIORITIES: dict[str, int] = {
    "water_resilience": 25,
    "soil_health_potential": 25,
    "yield_stability_proxy": 25,
    "labor_feasibility": 25,
}


def default_farmer_priorities() -> PriorityPoints:
    """Create equal four-criterion priorities without sharing mutable model state."""

    return PriorityPoints(**DEFAULT_FARMER_PRIORITIES)


class LocationCoordinates(BaseModel):
    """Private coordinate pair stored on one curated supported-location record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SupportedLocationSeed(BaseModel):
    """Curated place point, provenance, and display metadata loaded into MongoDB."""

    model_config = ConfigDict(extra="forbid", frozen=True)

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
