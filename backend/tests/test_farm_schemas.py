"""Validation and safe serialization tests for NY-19 farm and location DTOs."""

import pytest
from beanie import Document, PydanticObjectId
from pydantic import ValidationError

from app.database.registry import load_document_models
from app.farms.contracts import (
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
    """Return an explicit unknown-history draft using seeded catalog keys."""

    return {
        "name": "North field",
        "location_key": "ejura",
        "soil_texture_key": "unknown",
        "irrigation_access_key": "unknown",
        "history_status": "unknown",
    }


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


def test_create_keeps_only_supported_farm_inputs_and_preserves_unknowns() -> None:
    profile = FarmCreate.model_validate(valid_profile())

    assert profile.farmer_priorities is None
    assert profile.soil_texture_key == "unknown"
    assert profile.irrigation_access_key == "unknown"
    assert profile.crop_history == []
    assert profile.history_status == "unknown"


def test_create_trims_profile_fields_and_accepts_only_a_catalog_key() -> None:
    profile = FarmCreate.model_validate(
        {
            **valid_profile(),
            "name": "  North field  ",
            "location_key": "  ejura  ",
            "soil_texture_key": "  loamy  ",
            "history_status": "complete",
            "crop_history": [
                {
                    "crop_key": "  maize  ",
                    "sequence_order": 1,
                    "start_date": "2024-03-15",
                    "end_date": "2024-07-15",
                }
            ],
        }
    )

    assert profile.name == "North field"
    assert profile.location_key == "ejura"
    assert profile.soil_texture_key == "loamy"
    assert profile.crop_history[0].crop_key == "maize"

    with_priorities = FarmCreate.model_validate(
        {
            **valid_profile(),
            "farmer_priorities": {
                "water_resilience": 40,
                "soil_health_potential": 30,
                "yield_stability_proxy": 20,
                "labor_feasibility": 10,
            },
        }
    )
    assert with_priorities.farmer_priorities.water_resilience == 40

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
        FarmUpdate.model_validate({"farmer_priorities": {"water_resilience": 100}})
    priorities = FarmUpdate.model_validate(
        {
            "farmer_priorities": {
                "water_resilience": 40,
                "soil_health_potential": 30,
                "yield_stability_proxy": 20,
                "labor_feasibility": 10,
            }
        }
    )
    assert priorities.farmer_priorities.water_resilience == 40

    clear_optional_field = FarmUpdate.model_validate({"earliest_available_date": None})
    assert clear_optional_field.model_dump(exclude_unset=True) == {"earliest_available_date": None}


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
    assert farm_response["farmer_priorities"]["water_resilience"] == 25
    assert farm_response["history_status"] == "legacy_unresolved"
    assert "current_practice" not in farm_response


def test_legacy_text_stays_internal_after_owner_resolves_the_profile() -> None:
    farm = Farm.model_construct(
        id=PydanticObjectId(),
        owner_user_id=PydanticObjectId(),
        name="Old plot",
        location_key="ejura",
        previous_crops=["maize"],
        soil_texture="loam",
        history_status="legacy_unresolved",
    )

    unresolved = FarmResponse.from_document(farm, location_label="Ejura")
    assert unresolved.legacy_unresolved_inputs is not None
    assert unresolved.legacy_unresolved_inputs.previous_crops == ["maize"]

    resolved = farm.model_copy(update={"schema_version": "farm-v2", "history_status": "complete"})
    public_resolved = FarmResponse.from_document(resolved, location_label="Ejura")
    assert public_resolved.legacy_unresolved_inputs is None
