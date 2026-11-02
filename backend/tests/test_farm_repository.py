"""Repository query tests proving ownership and catalog constraints are applied."""

import asyncio
from typing import Any

import pytest
from beanie import PydanticObjectId, UpdateResponse

from app.repositories.farms import FarmRepository, UnsupportedFarmLocation
from app.schemas.farms import FarmCreate, FarmUpdate


class FakeFarmDocument:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)
        self.inserted = False

    async def insert(self) -> "FakeFarmDocument":
        self.inserted = True
        return self


class FakeCursor:
    def __init__(self, result: list[FakeFarmDocument]) -> None:
        self.result = result

    async def to_list(self) -> list[FakeFarmDocument]:
        return self.result


class FakeUpdateQuery:
    def __init__(self, result: FakeFarmDocument | None) -> None:
        self.result = result
        self.update_values: dict[str, Any] | None = None
        self.response_type: UpdateResponse | None = None

    def __await__(self) -> Any:
        async def return_result() -> FakeFarmDocument | None:
            return self.result

        return return_result().__await__()

    async def update(
        self,
        update_values: dict[str, Any],
        *,
        response_type: UpdateResponse,
    ) -> FakeFarmDocument | None:
        self.update_values = update_values
        self.response_type = response_type
        return self.result


class FakeFarmModel:
    def __init__(self, results: list[FakeFarmDocument] | None = None) -> None:
        self.results = results or []
        self.created: list[FakeFarmDocument] = []
        self.filters: list[dict[str, object]] = []
        self.update_query = FakeUpdateQuery(None)

    def __call__(self, **values: Any) -> FakeFarmDocument:
        farm = FakeFarmDocument(**values)
        self.created.append(farm)
        return farm

    def find(self, query: dict[str, object]) -> FakeCursor:
        self.filters.append(query)
        return FakeCursor(self.results)

    def find_one(self, query: dict[str, object]) -> FakeUpdateQuery:
        self.filters.append(query)
        return self.update_query


class FakeSupportedLocationModel:
    def __init__(self, selectable_keys: set[str] | None = None) -> None:
        self.selectable_keys = (
            {"ejura", "anyinasu", "kintampo"} if selectable_keys is None else selectable_keys
        )
        self.filters: list[dict[str, object]] = []

    async def find_one(self, query: dict[str, object]) -> object | None:
        self.filters.append(query)
        if query["location_key"] in self.selectable_keys and query["is_selectable"] is True:
            return object()
        return None


def profile_create() -> FarmCreate:
    """Return contract-valid, non-real fixture input."""

    return FarmCreate.model_validate({"name": "Test field", "location_key": "ejura"})


def test_create_sets_owner_and_stores_only_catalog_reference() -> None:
    owner_user_id = PydanticObjectId()
    model = FakeFarmModel()
    locations = FakeSupportedLocationModel()

    created = asyncio.run(
        FarmRepository(model, locations).create(
            owner_user_id=owner_user_id,
            profile=profile_create(),
        )
    )

    assert created.owner_user_id == owner_user_id
    assert created.location_key == "ejura"
    assert "coordinates" not in created.__dict__
    assert created.inserted
    assert model.created == [created]
    assert locations.filters == [{"location_key": "ejura", "is_selectable": True}]


def test_create_rejects_a_missing_or_disabled_catalog_location() -> None:
    model = FakeFarmModel()
    locations = FakeSupportedLocationModel(selectable_keys=set())

    with pytest.raises(UnsupportedFarmLocation):
        asyncio.run(
            FarmRepository(model, locations).create(
                owner_user_id=PydanticObjectId(),
                profile=profile_create(),
            )
        )

    assert model.created == []


def test_list_query_contains_only_the_authenticated_owner() -> None:
    owner_user_id = PydanticObjectId()
    expected = [FakeFarmDocument(owner_user_id=owner_user_id)]
    model = FakeFarmModel(results=expected)

    results = asyncio.run(FarmRepository(model).list_by_owner(owner_user_id=owner_user_id))

    assert results == expected
    assert model.filters == [{"owner_user_id": owner_user_id}]


def test_get_query_requires_both_farm_id_and_owner() -> None:
    farm_id = PydanticObjectId()
    owner_user_id = PydanticObjectId()
    model = FakeFarmModel()

    result = asyncio.run(
        FarmRepository(model).get_by_owner(farm_id=farm_id, owner_user_id=owner_user_id)
    )

    assert result is None
    assert model.filters == [{"_id": farm_id, "owner_user_id": owner_user_id}]


def test_update_query_requires_both_ids_and_updates_only_allowed_fields() -> None:
    farm_id = PydanticObjectId()
    owner_user_id = PydanticObjectId()
    updated_farm = FakeFarmDocument(id=farm_id, owner_user_id=owner_user_id)
    model = FakeFarmModel()
    model.update_query = FakeUpdateQuery(updated_farm)

    updated = asyncio.run(
        FarmRepository(model).update_by_owner(
            farm_id=farm_id,
            owner_user_id=owner_user_id,
            changes=FarmUpdate.model_validate({"name": "South field"}),
        )
    )

    assert updated is updated_farm
    assert model.filters == [{"_id": farm_id, "owner_user_id": owner_user_id}]
    assert model.update_query.update_values is not None
    assert model.update_query.update_values["$set"]["name"] == "South field"
    assert "owner_user_id" not in model.update_query.update_values["$set"]
    assert model.update_query.response_type is UpdateResponse.NEW_DOCUMENT


def test_update_validates_a_new_location_before_writing() -> None:
    model = FakeFarmModel()
    locations = FakeSupportedLocationModel(selectable_keys=set())

    with pytest.raises(UnsupportedFarmLocation):
        asyncio.run(
            FarmRepository(model, locations).update_by_owner(
                farm_id=PydanticObjectId(),
                owner_user_id=PydanticObjectId(),
                changes=FarmUpdate.model_validate({"location_key": "ejura"}),
            )
        )

    assert model.filters == []
