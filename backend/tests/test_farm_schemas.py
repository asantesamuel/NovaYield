"""Validation and safe serialization tests for NY-19 farm DTOs."""

import pytest
from beanie import Document, PydanticObjectId
from pydantic import ValidationError

from app.database.registry import load_document_models
from app.farms.contracts import DEFAULT_FARMER_PRIORITIES, FarmLocationData
from app.models.farms import FARM_OWNER_INDEX_NAME, Farm
from app.schemas.farms import FarmCreate, FarmLocationSummary, FarmResponse, FarmUpdate


def valid_profile() -> dict[str, object]:
    """Return the smallest profile that satisfies the current contract."""

    return {
        "name": "North field",
        "location": {
            "label": "Synthetic test location",
            "latitude": 0.0,
            "longitude": 0.0,
        },
    }


def test_farm_document_registers_and_declares_owner_index() -> None:
    assert issubclass(Farm, Document)
    assert Farm in load_document_models()
    assert Farm.Settings.name == "farms"
    assert any(index.document["name"] == FARM_OWNER_INDEX_NAME for index in Farm.Settings.indexes)
    owner_index = next(
        index for index in Farm.Settings.indexes if index.document["name"] == FARM_OWNER_INDEX_NAME
    )
    assert owner_index.document["key"] == {"owner_user_id": 1}
    assert not owner_index.document.get("unique", False)


def test_create_defaults_to_equal_priorities_and_preserves_unknown_inputs() -> None:
    profile = FarmCreate.model_validate(valid_profile())

    assert profile.farmer_priorities.model_dump() == DEFAULT_FARMER_PRIORITIES
    assert profile.soil_texture is None
    assert profile.irrigation_access is None
    assert profile.previous_crops is None
    assert profile.current_practice is None


def test_create_trims_text_and_validates_private_location_coordinates() -> None:
    profile = FarmCreate.model_validate(
        {
            **valid_profile(),
            "name": "  North field  ",
            "location": {
                "label": "  Synthetic test location  ",
                "latitude": 0.0,
                "longitude": 0.0,
            },
            "soil_texture": "  sandy loam  ",
            "previous_crops": ["  maize  ", "cowpea"],
        }
    )

    assert profile.name == "North field"
    assert profile.location.label == "Synthetic test location"
    assert profile.soil_texture == "sandy loam"
    assert profile.previous_crops == ["maize", "cowpea"]


@pytest.mark.parametrize(
    "location",
    [
        {"label": "Ejura", "latitude": 7.3},
        {"label": "Ejura", "latitude": 91, "longitude": 0},
        {"label": "Ejura", "latitude": 0, "longitude": 181},
    ],
)
def test_location_rejects_partial_or_out_of_range_coordinates(
    location: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        FarmLocationData.model_validate(location)


def test_location_rejects_coordinate_text_that_would_echo_in_responses() -> None:
    with pytest.raises(ValidationError):
        FarmLocationData.model_validate({"label": "Synthetic location 12.3456, -1.2345"})

    with pytest.raises(ValidationError):
        FarmLocationSummary.model_validate({"label": "Synthetic location 12.3456"})


def test_create_rejects_incomplete_profile_and_client_supplied_owner() -> None:
    with pytest.raises(ValidationError):
        FarmCreate.model_validate({"location": {"label": "Ejura"}})

    with pytest.raises(ValidationError):
        FarmCreate.model_validate(
            {"name": "Test field", "location": {"label": "Synthetic test location"}}
        )

    with pytest.raises(ValidationError):
        FarmCreate.model_validate({**valid_profile(), "owner_user_id": str(PydanticObjectId())})


def test_update_requires_changes_and_cannot_clear_required_fields() -> None:
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({})
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({"name": None})
    with pytest.raises(ValidationError):
        FarmUpdate.model_validate({"farmer_priorities": None})

    clear_optional_field = FarmUpdate.model_validate({"soil_texture": None})
    assert clear_optional_field.model_dump(exclude_unset=True) == {"soil_texture": None}


def test_public_response_omits_owner_and_precise_coordinates() -> None:
    farm = Farm.model_construct(
        id=PydanticObjectId(),
        owner_user_id=PydanticObjectId(),
        name="North field",
        location=FarmLocationData(
            label="Synthetic test location",
            latitude=0.0,
            longitude=0.0,
        ),
    )

    public_response = FarmResponse.from_document(farm).model_dump(mode="json")

    assert public_response["id"] == str(farm.id)
    assert public_response["location"] == {"label": "Synthetic test location"}
    assert "owner_user_id" not in public_response
    assert "latitude" not in str(public_response)
    assert "longitude" not in str(public_response)
    assert '"latitude": 0.0' not in str(public_response)
    assert '"longitude": 0.0' not in str(public_response)
