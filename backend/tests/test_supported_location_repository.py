"""Tests for idempotently seeding and listing the private location catalog."""

import asyncio
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.repositories.supported_locations import SupportedLocationRepository


class FakeLocationDocument:
    def __init__(self, owner: "FakeLocationModel", **values: Any) -> None:
        self.owner = owner
        self.__dict__.update(values)

    async def insert(self) -> "FakeLocationDocument":
        key = self.location_key
        if key in self.owner.records:
            raise DuplicateKeyError("duplicate supported-location key")
        self.owner.records[key] = self
        return self


class FakeLocationCursor:
    def __init__(self, records: list[FakeLocationDocument]) -> None:
        self.records = records
        self.sort_values: list[tuple[str, int]] | None = None

    def sort(self, values: list[tuple[str, int]]) -> "FakeLocationCursor":
        self.sort_values = values
        return self

    async def to_list(self) -> list[FakeLocationDocument]:
        records = list(self.records)
        for field_name, direction in reversed(self.sort_values or []):
            records.sort(key=lambda record: getattr(record, field_name), reverse=direction < 0)
        return records


class FakeLocationModel:
    def __init__(self) -> None:
        self.records: dict[str, FakeLocationDocument] = {}
        self.filters: list[dict[str, object]] = []

    def __call__(self, **values: Any) -> FakeLocationDocument:
        return FakeLocationDocument(self, **values)

    async def find_one(self, query: dict[str, object]) -> FakeLocationDocument | None:
        self.filters.append(query)
        record = self.records.get(str(query["location_key"]))
        if record is None:
            return None
        if query.get("is_selectable") is True and not record.is_selectable:
            return None
        return record

    def find(self, query: dict[str, object]) -> FakeLocationCursor:
        self.filters.append(query)
        records = []
        for record in self.records.values():
            matches = True
            for field, value in query.items():
                actual = getattr(record, field)
                if isinstance(value, dict) and "$in" in value:
                    matches = actual in value["$in"]
                else:
                    matches = actual == value
                if not matches:
                    break
            if matches:
                records.append(record)
        return FakeLocationCursor(records)


def test_seed_missing_is_idempotent_and_does_not_overwrite_reviewed_records() -> None:
    model = FakeLocationModel()
    repository = SupportedLocationRepository(model)

    inserted_first_run = asyncio.run(repository.seed_missing())
    model.records["ejura"].validation_status = "reviewed"
    model.records["ejura"].label = "Reviewed Ejura label"
    inserted_second_run = asyncio.run(repository.seed_missing())

    assert inserted_first_run == 3
    assert inserted_second_run == 0
    assert model.records["ejura"].validation_status == "reviewed"
    assert model.records["ejura"].label == "Reviewed Ejura label"
    assert model.records["ejura"].coordinates["latitude"] == 7.3856
    assert len(model.records) == 3


def test_catalog_lookup_requires_selectable_key_and_list_is_ordered() -> None:
    model = FakeLocationModel()
    repository = SupportedLocationRepository(model)
    asyncio.run(repository.seed_missing())
    model.records["anyinasu"].is_selectable = False

    locations = asyncio.run(repository.list_selectable())
    missing = asyncio.run(repository.get_selectable("unknown"))
    disabled = asyncio.run(repository.get_selectable("anyinasu"))

    assert [location.location_key for location in locations] == ["ejura", "kintampo"]
    assert missing is None
    assert disabled is None
    assert model.filters[-2:] == [
        {"location_key": "unknown", "is_selectable": True},
        {"location_key": "anyinasu", "is_selectable": True},
    ]


def test_existing_farm_location_can_be_resolved_even_if_disabled_and_keys_are_batched() -> None:
    model = FakeLocationModel()
    repository = SupportedLocationRepository(model)
    asyncio.run(repository.seed_missing())
    model.records["anyinasu"].is_selectable = False

    existing = asyncio.run(repository.get_by_key("anyinasu"))
    batch = asyncio.run(repository.list_by_keys({"ejura", "anyinasu"}))
    empty = asyncio.run(repository.list_by_keys(set()))

    assert existing is model.records["anyinasu"]
    assert {location.location_key for location in batch} == {"ejura", "anyinasu"}
    assert empty == []
    assert model.filters[-2:] == [
        {"location_key": "anyinasu"},
        {"location_key": {"$in": ["anyinasu", "ejura"]}},
    ]
