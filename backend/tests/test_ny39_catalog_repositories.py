"""Offline repository tests for idempotent catalog seed and lossless v1 marking."""

import asyncio
from types import SimpleNamespace
from typing import Any

from beanie import PydanticObjectId

from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.farm_reference_options import FarmReferenceRepository
from app.repositories.farms import FarmRepository


class FakeDocument:
    def __init__(self, model: "FakeModel", **fields: Any) -> None:
        self._model = model
        self.id = PydanticObjectId()
        self.__dict__.update(fields)

    async def insert(self) -> "FakeDocument":
        self._model.documents.append(self)
        return self


class FakeCursor:
    def __init__(self, documents: list[FakeDocument]) -> None:
        self.documents = documents

    def sort(self, _fields: Any) -> "FakeCursor":
        return self

    async def to_list(self) -> list[FakeDocument]:
        return self.documents


class FakeModel:
    def __init__(self, defaults: dict[str, Any] | None = None) -> None:
        self.documents: list[FakeDocument] = []
        self.defaults = defaults or {}

    def __call__(self, **fields: Any) -> FakeDocument:
        return FakeDocument(self, **{**self.defaults, **fields})

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor([doc for doc in self.documents if _matches(doc, query)])

    async def find_one(self, query: dict[str, Any]) -> FakeDocument | None:
        return next((doc for doc in self.documents if _matches(doc, query)), None)


def _matches(doc: FakeDocument, query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = getattr(doc, key, None)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def test_catalog_seed_is_idempotent_and_candidate_bundle_uses_same_crops() -> None:
    crops = FakeModel({"catalog_status": "active"})
    profiles = FakeModel({"is_active": True, "maturity_days": None})
    calendars = FakeModel()
    references = FakeModel({"selectable": True})
    catalog = CropCatalogRepository(crops, profiles, calendars)
    reference_catalog = FarmReferenceRepository(references)

    async def run() -> tuple[dict[str, int], dict[str, int], int, int, Any]:
        first = await catalog.seed_missing()
        second = await catalog.seed_missing()
        reference_first = await reference_catalog.seed_missing()
        reference_second = await reference_catalog.seed_missing()
        bundles = await catalog.list_recommendation_candidates(location_key="ejura")
        return first, second, reference_first, reference_second, bundles

    first, second, reference_first, reference_second, bundles = asyncio.run(run())
    assert first == {"crops": 8, "profiles": 13, "calendars": 4}
    assert second == {"crops": 0, "profiles": 0, "calendars": 0}
    assert (reference_first, reference_second) == (8, 0)
    assert {bundle.crop.crop_key for bundle in bundles} == {
        "maize",
        "cowpea",
        "groundnut",
        "cassava",
        "yam",
        "rice",
    }
    assert all(bundle.active_profiles for bundle in bundles)
    assert all(calendar.planting_window is None for calendar in calendars.documents)
    assert all(
        profile.maturity_days is None
        for profile in profiles.documents
        if profile.variety_key is None
    )


def test_seed_preserves_curated_active_profile_and_calendar_revisions() -> None:
    crops = FakeModel({"catalog_status": "active"})
    profiles = FakeModel({"is_active": True, "maturity_days": None})
    calendars = FakeModel()
    catalog = CropCatalogRepository(crops, profiles, calendars)

    async def run() -> tuple[dict[str, int], dict[str, int], Any, Any]:
        maize = crops(crop_key="maize", common_name="Curated Maize")
        await maize.insert()
        curated_profile = profiles(
            crop_id=maize.id,
            variety_key=None,
            production_system_key=None,
            revision=2,
            is_active=True,
            evidence_status="locally_reviewed",
        )
        await curated_profile.insert()
        curated_calendar = calendars(
            location_key="ejura",
            crop_id=maize.id,
            profile_revision_id=None,
            season_key="major-rainy-season",
            calendar_version="curated-v2",
            is_active=True,
            status="locally_reviewed",
        )
        await curated_calendar.insert()
        first = await catalog.seed_missing()
        second = await catalog.seed_missing()
        return first, second, curated_profile, curated_calendar

    first, second, curated_profile, curated_calendar = asyncio.run(run())

    assert first == {"crops": 7, "profiles": 12, "calendars": 3}
    assert second == {"crops": 0, "profiles": 0, "calendars": 0}
    assert [
        profile
        for profile in profiles.documents
        if profile.crop_id == curated_profile.crop_id
        and profile.variety_key is None
        and profile.production_system_key is None
    ] == [curated_profile]
    assert [
        calendar
        for calendar in calendars.documents
        if calendar.location_key == curated_calendar.location_key
        and calendar.crop_id == curated_calendar.crop_id
        and calendar.profile_revision_id is None
        and calendar.season_key == curated_calendar.season_key
    ] == [curated_calendar]


class FakeLegacyCollection:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records

    async def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> Any:
        assert query == {
            "schema_version": {"$exists": False},
            "crop_history": {"$exists": False},
        }
        count = 0
        for record in self.records:
            if "schema_version" in record or "crop_history" in record:
                continue
            record.update(update["$set"])
            count += 1
        return SimpleNamespace(modified_count=count)


class FakeLegacyFarmModel:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.collection = FakeLegacyCollection(records)

    def get_pymongo_collection(self) -> FakeLegacyCollection:
        return self.collection


def test_legacy_migration_marks_only_old_records_without_inventing_history() -> None:
    records = [
        {
            "name": "Old plot",
            "previous_crops": ["beans"],
            "current_practice": "maize",
            "soil_texture": "sandy loam",
        },
        {"name": "New plot", "schema_version": "farm-v2", "crop_history": []},
    ]
    repository = FarmRepository(farm_model=FakeLegacyFarmModel(records))

    assert asyncio.run(repository.mark_legacy_unresolved()) == 1
    assert asyncio.run(repository.mark_legacy_unresolved()) == 0
    assert records[0]["history_status"] == "legacy_unresolved"
    assert records[0]["schema_version"] == "farm-v1"
    assert records[0]["previous_crops"] == ["beans"]
    assert records[0]["current_practice"] == "maize"
    assert "crop_history" not in records[0]
    assert records[1] == {"name": "New plot", "schema_version": "farm-v2", "crop_history": []}
