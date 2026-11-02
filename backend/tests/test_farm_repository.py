"""Repository query tests proving owner constraints are built into Mongo filters."""

import asyncio
from typing import Any

from beanie import PydanticObjectId, UpdateResponse

from app.repositories.farms import FarmRepository
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


def profile_create() -> FarmCreate:
    """Return synthetic mechanics-only input, not an asserted farm record."""

    return FarmCreate.model_validate(
        {"name": "Test field", "location": {"label": "Synthetic test location"}}
    )


def test_create_sets_owner_from_explicit_authenticated_owner() -> None:
    owner_user_id = PydanticObjectId()
    model = FakeFarmModel()

    created = asyncio.run(
        FarmRepository(model).create(owner_user_id=owner_user_id, profile=profile_create())
    )

    assert created.owner_user_id == owner_user_id
    assert created.inserted
    assert model.created == [created]


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
