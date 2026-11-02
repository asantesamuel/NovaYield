"""Validation and safe serialization tests for NY-19 farm and location DTOs."""

import pytest
from beanie import Document, PydanticObjectId
from pydantic import ValidationError

from app.database.registry import load_document_models
from app.farms.contracts import (
    DEFAULT_FARMER_PRIORITIES,
    LocationCoordinates,
    default_farmer_priorities,
)
from app.farms.location_catalog import SUPPORTED_LOCATION_SEEDS
from app.models.farms import FARM_OWNER_INDEX_NAME, Farm
from app.models.supported_locations import (
    SUPPORTED_LOCATION_KEY_INDEX_NAME,
    SUPPORTED_LOCATION_ORDER_INDEX_NAME,
    SupportedLocation,
)
from app.schemas.farms import (
    FarmCreate,
    FarmResponse,
    FarmUpdate,
    SupportedLocationOption,
)


def valid_profile() -> dict[str, object]:
    """Return a mechanics-only profile using the seeded Ejura catalog key."""

    return {"name": "North field", "location_key": "ejura"}


def test_farm_document_registers_and_declares_owner_index() -> None:
    assert issubclass(Farm, Document)
    assert Farm in load_document_models()
    assert Farm.Settings.name == "farms"
    owner_index = next(
        index for index in Farm.Settings.indexes if index.document["name"] == FARM_OWNER_INDEX_NAME
    )
    assert owner_index.document["key"] == {"owner_user_id": 1}
    assert not owner_index.document.get("unique", False)


def test_supported_location_document_registers_unique_lookup_and_order_indexes() -> None:
    assert issubclass(SupportedLocation, Document)
    assert SupportedLocation in load_document_models()
    assert SupportedLocation.Settings.name == "supported_locations"
    indexes = {
        index.document["name"]: index.document for index in SupportedLocation.Settings.indexes
    }
    assert indexes[SUPPORTED_LOCATION_KEY_INDEX_NAME]["key"] == {"location_key": 1}
    assert indexes[SUPPORTED_LOCATION_KEY_INDEX_NAME]["unique"] is True
    assert indexes[SUPPORTED_LOCATION_ORDER_INDEX_NAME]["key"] == {
        "is_selectable": 1,
        "sort_order": 1,
        "location_key": 1,
    }


def test_curated_points_are_provisional_sourced_and_in_research_order() -> None:
    assert [seed.location_key for seed in SUPPORTED_LOCATION_SEEDS] == [
        "ejura",
        "anyinasu",
        "kintampo",
    ]
    ejura, anyinasu, kintampo = SUPPORTED_LOCATION_SEEDS
    assert (ejura.coordinates.latitude, ejura.coordinates.longitude) == (7.3856, -1.3562)
    assert (anyinasu.coordinates.latitude, anyinasu.coordinates.longitude) == (
        7.23705,
        -1.57696,
    )
    assert (kintampo.coordinates.latitude, kintampo.coordinates.longitude) == (8.0537, -1.7289)
    assert all(seed.validation_status == "provisional" for seed in SUPPORTED_LOCATION_SEEDS)
    assert all(seed.coordinate_source_url.scheme == "https" for seed in SUPPORTED_LOCATION_SEEDS)
    assert kintampo.administrative_area == "Kintampo North Municipal District"


def test_location_coordinate_pair_is_required_and_bounded() -> None:
    with pytest.raises(ValidationError):
        LocationCoordinates.model_validate({"latitude": 7.3})
    with pytest.raises(ValidationError):
        LocationCoordinates.model_validate({"latitude": 91, "longitude": 0})
    with pytest.raises(ValidationError):
        LocationCoordinates.model_validate({"latitude": 0, "longitude": 181})


def test_create_defaults_to_equal_priorities_and_preserves_unknown_inputs() -> None:
    profile = FarmCreate.model_validate(valid_profile())

    assert profile.farmer_priorities.model_dump() == DEFAULT_FARMER_PRIORITIES
    assert profile.soil_texture is None
    assert profile.irrigation_access is None
    assert profile.previous_crops is None
    assert profile.current_practice is None


def test_create_trims_profile_fields_and_accepts_only_a_catalog_key() -> None:
    profile = FarmCreate.model_validate(
        {
            **valid_profile(),
            "name": "  North field  ",
            "location_key": "  ejura  ",
            "soil_texture": "  sandy loam  ",
            "previous_crops": ["  maize  ", "cowpea"],
        }
    )

    assert profile.name == "North field"
    assert profile.location_key == "ejura"
    assert profile.soil_texture == "sandy loam"
    assert profile.previous_crops == ["maize", "cowpea"]

    with pytest.raises(ValidationError):
        FarmCreate.model_validate({"name": "North field", "location_key": "ejura", "latitude": 7.3})
    with pytest.raises(ValidationError):
        FarmCreate.model_validate({"name": "North field", "location_key": "../ejura"})


def test_create_rejects_incomplete_profile_and_client_supplied_owner() -> None:
    with pytest.raises(ValidationError):
        FarmCreate.model_validate({"location_key": "ejura"})
    with pytest.raises(ValidationError):
        FarmCreate.model_validate({"name": "Test field"})
    with pytest.raises(ValidationError):
        FarmCreate.model_validate({**valid_profile(), "owner_user_id": str(PydanticObjectId())})


def test_update_requires_changes_and_cannot_clear_required_fields() -> None:
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({})
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({"name": None})
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({"location_key": None})
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({"farmer_priorities": None})

    clear_optional_field = FarmUpdate.model_validate({"soil_texture": None})
    assert clear_optional_field.model_dump(exclude_unset=True) == {"soil_texture": None}


def test_public_location_and_farm_responses_never_include_coordinates_or_owner() -> None:
    farm = Farm.model_construct(
        id=PydanticObjectId(),
        owner_user_id=PydanticObjectId(),
        name="North field",
        location_key="ejura",
        farmer_priorities=default_farmer_priorities(),
    )
    location = SupportedLocation.model_construct(
        location_key="ejura",
        label="Ejura",
        coordinates=LocationCoordinates(latitude=7.3856, longitude=-1.3562),
    )

    location_response = SupportedLocationOption.from_document(location).model_dump(mode="json")
    farm_response = FarmResponse.from_document(farm, location_label="Ejura").model_dump(mode="json")

    assert location_response == {"location_key": "ejura", "label": "Ejura"}
    assert farm_response["location"] == {"location_key": "ejura", "label": "Ejura"}
    assert "owner_user_id" not in farm_response
    assert "coordinates" not in str(location_response)
    assert "latitude" not in str(farm_response)
    assert "longitude" not in str(farm_response)
