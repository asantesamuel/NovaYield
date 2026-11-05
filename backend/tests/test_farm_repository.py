"""Farm repository tests for catalog resolution, ownership and context CAS."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest
from beanie import PydanticObjectId

from app.models.crop_catalog import Crop
from app.models.farms import FarmEnvironmentalContextState, HistoryGap
from app.repositories.farms import (
    FarmRepository,
    FarmRevisionConflict,
    UnsupportedCropProfile,
    UnsupportedFarmLocation,
    UnsupportedFarmReference,
    UnsupportedHistoryCrop,
)
from app.schemas.farms import FarmCreate, FarmUpdate


class FakeFarmDocument:
    def __init__(self, model: "FakeFarmModel", **values: Any) -> None:
        self._model = model
        self.id = PydanticObjectId()
        self.__dict__.update(values)

    async def insert(self) -> "FakeFarmDocument":
        self._model.records[self.id] = self
        return self


class FakeQuery:
    def __init__(self, model: "FakeFarmModel", filter_values: dict[str, Any]) -> None:
        self.model = model
        self.filter_values = filter_values

    def _match(self) -> FakeFarmDocument | None:
        def field_value(document: FakeFarmDocument, key: str) -> Any:
            if key == "_id":
                return document.id
            value: Any = document
            for part in key.split("."):
                value = value.get(part) if isinstance(value, dict) else getattr(value, part, None)
            return value

        def matches(document: FakeFarmDocument, query: dict[str, Any]) -> bool:
            for key, value in query.items():
                if key == "$or":
                    if not any(matches(document, branch) for branch in value):
                        return False
                elif isinstance(value, dict) and "$exists" in value:
                    if (key in document.__dict__) != value["$exists"]:
                        return False
                elif isinstance(value, dict) and "$nin" in value:
                    if field_value(document, key) in value["$nin"]:
                        return False
                elif field_value(document, key) != value:
                    return False
            return True

        for document in self.model.records.values():
            if matches(document, self.filter_values):
                return document
        return None

    def __await__(self) -> Any:
        async def result() -> FakeFarmDocument | None:
            return self._match()

        return result().__await__()

    async def update(
        self, changes: dict[str, Any], *, response_type: Any
    ) -> FakeFarmDocument | None:
        self.model.last_update_filter = self.filter_values
        if self.model.before_update is not None:
            callback = self.model.before_update
            self.model.before_update = None
            callback()
        document = self._match()
        if document is None:
            return None
        for key, value in changes.get("$set", {}).items():
            setattr(document, key, value)
        for key, value in changes.get("$inc", {}).items():
            setattr(document, key, getattr(document, key, 0) + value)
        return document


class FakeCursor:
    def __init__(self, results: list[FakeFarmDocument]) -> None:
        self.results = results

    async def to_list(self) -> list[FakeFarmDocument]:
        return self.results


class FakeFarmModel:
    def __init__(self) -> None:
        self.records: dict[PydanticObjectId, FakeFarmDocument] = {}
        self.last_update_filter: dict[str, Any] | None = None
        self.before_update: Any = None

    def __call__(self, **values: Any) -> FakeFarmDocument:
        return FakeFarmDocument(self, **values)

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [
                doc
                for doc in self.records.values()
                if all(getattr(doc, key, None) == value for key, value in query.items())
            ]
        )

    def find_one(self, query: dict[str, Any]) -> FakeQuery:
        return FakeQuery(self, query)


class FakeSupportedLocations:
    def __init__(self, keys: set[str] | None = None) -> None:
        self.keys = {"ejura", "anyinasu", "kintampo"} if keys is None else keys

    async def find_one(self, query: dict[str, Any]) -> object | None:
        return object() if query["location_key"] in self.keys else None


class FakeCropCatalog:
    def __init__(self) -> None:
        self.crops = {
            key: Crop.model_construct(
                id=PydanticObjectId(),
                crop_key=key,
                common_name=key.title(),
                catalog_status="active",
                history_selectable=True,
            )
            for key in ("maize", "cowpea", "plantain")
        }

    async def get_history_crop(self, crop_key: str) -> Crop | None:
        crop = self.crops.get(crop_key)
        return crop if crop is not None and crop.catalog_status == "active" else None

    async def get_active_profile(self, *args: Any, **kwargs: Any) -> object | None:
        return None


class FakeReferences:
    async def get_selectable(self, kind: str, key: str) -> object | None:
        if kind == "soil_texture" and key in {"loamy", "unknown"}:
            return object()
        if kind == "irrigation_access" and key in {"none", "unknown"}:
            return object()
        return None


def repository(
    model: FakeFarmModel | None = None,
    *,
    location_keys: set[str] | None = None,
) -> tuple[FarmRepository, FakeFarmModel]:
    model = model or FakeFarmModel()
    return (
        FarmRepository(
            model,
            FakeSupportedLocations(location_keys),
            crop_repository=FakeCropCatalog(),
            reference_repository=FakeReferences(),
        ),
        model,
    )


def profile_create(**overrides: Any) -> FarmCreate:
    fields: dict[str, Any] = {
        "name": "Test field",
        "location_key": "ejura",
        "soil_texture_key": "loamy",
        "irrigation_access_key": "none",
        "history_status": "complete",
        "crop_history": [
            {
                "crop_key": "maize",
                "sequence_order": 1,
                "start_date": "2024-03-15",
                "end_date": "2024-07-15",
            }
        ],
    }
    fields.update(overrides)
    return FarmCreate.model_validate(fields)


def test_create_sets_owner_and_resolves_canonical_crop_reference() -> None:
    repo, model = repository()
    owner = PydanticObjectId()
    farm = asyncio.run(repo.create(owner_user_id=owner, profile=profile_create()))

    assert farm.id in model.records
    assert farm.owner_user_id == owner
    assert farm.schema_version == "farm-v2"
    assert farm.revision == 1
    assert farm.crop_history[0].crop_id == repo._crops.crops["maize"].id
    assert farm.crop_history[0].crop_key_snapshot == "maize"
    assert farm.crop_history[0].start_date == date(2024, 3, 15)
    assert farm.environmental_context.period.start_date == date(2023, 7, 15)
    assert farm.environmental_context.status == "pending"
    assert "coordinates" not in farm.__dict__


def test_create_rejects_missing_location_reference_or_crop() -> None:
    missing_location, model = repository(location_keys=set())
    with pytest.raises(UnsupportedFarmLocation):
        asyncio.run(
            missing_location.create(owner_user_id=PydanticObjectId(), profile=profile_create())
        )
    assert not model.records

    repo, model = repository()
    with pytest.raises(UnsupportedFarmReference):
        asyncio.run(
            repo.create(
                owner_user_id=PydanticObjectId(),
                profile=profile_create(soil_texture_key="unlisted"),
            )
        )
    with pytest.raises(UnsupportedHistoryCrop):
        asyncio.run(
            repo.create(
                owner_user_id=PydanticObjectId(),
                profile=profile_create(
                    crop_history=[
                        {
                            "crop_key": "unlisted",
                            "sequence_order": 1,
                            "start_date": "2024-03-15",
                            "end_date": "2024-07-15",
                        }
                    ]
                ),
            )
        )
    assert not model.records


def test_list_get_and_update_are_owner_scoped() -> None:
    repo, model = repository()
    owner = PydanticObjectId()
    other = PydanticObjectId()
    farm = asyncio.run(repo.create(owner_user_id=owner, profile=profile_create()))

    assert asyncio.run(repo.list_by_owner(owner_user_id=other)) == []
    assert asyncio.run(repo.get_by_owner(farm_id=farm.id, owner_user_id=other)) is None
    assert (
        asyncio.run(
            repo.update_by_owner(
                farm_id=farm.id,
                owner_user_id=other,
                changes=FarmUpdate.model_validate({"name": "Stolen"}),
            )
        )
        is None
    )
    updated = asyncio.run(
        repo.update_by_owner(
            farm_id=farm.id,
            owner_user_id=owner,
            changes=FarmUpdate.model_validate({"name": "South field"}),
        )
    )
    assert updated.name == "South field"
    assert updated.revision == 2
    assert model.last_update_filter == {
        "_id": farm.id,
        "owner_user_id": owner,
        "revision": 1,
    }


def test_concurrent_patch_rejects_stale_merge_instead_of_losing_an_edit() -> None:
    repo, model = repository()
    owner = PydanticObjectId()
    farm = asyncio.run(repo.create(owner_user_id=owner, profile=profile_create()))

    def concurrent_edit() -> None:
        farm.revision += 1
        farm.name = "Another editor's name"

    model.before_update = concurrent_edit
    with pytest.raises(FarmRevisionConflict):
        asyncio.run(
            repo.update_by_owner(
                farm_id=farm.id,
                owner_user_id=owner,
                changes=FarmUpdate.model_validate({"name": "Stale name"}),
            )
        )
    assert farm.name == "Another editor's name"
    assert farm.revision == 2


def test_inactive_saved_history_and_verified_gap_survive_unrelated_patch() -> None:
    repo, _ = repository()
    owner = PydanticObjectId()
    farm = asyncio.run(
        repo.create(
            owner_user_id=owner,
            profile=profile_create(
                history_status="needs_review",
                crop_history=[
                    {
                        "crop_key": "maize",
                        "sequence_order": 1,
                        "start_date": "2024-03-15",
                        "end_date": "2024-07-15",
                    },
                    {
                        "crop_key": "cowpea",
                        "sequence_order": 2,
                        "start_date": "2024-09-01",
                        "end_date": "2024-12-01",
                    },
                ],
            ),
        )
    )
    original_crop_id = farm.crop_history[0].crop_id
    repo._crops.crops["maize"].catalog_status = "inactive"
    farm.declared_gaps = [
        HistoryGap(
            start_date=date(2024, 7, 16),
            end_date=date(2024, 8, 31),
            status="fallow",
            source="extension_verified",
            reviewer_ref="test-reviewer",
            reviewed_at=datetime(2024, 8, 1, tzinfo=UTC),
        )
    ]

    updated = asyncio.run(
        repo.update_by_owner(
            farm_id=farm.id,
            owner_user_id=owner,
            changes=FarmUpdate.model_validate({"name": "Corrected name"}),
        )
    )
    assert updated.crop_history[0]["crop_id"] == original_crop_id
    assert updated.declared_gaps[0]["source"] == "extension_verified"
    assert updated.declared_gaps[0]["reviewer_ref"] == "test-reviewer"


def test_system_only_history_scope_must_resolve_to_an_active_profile() -> None:
    repo, model = repository()
    with pytest.raises(UnsupportedCropProfile):
        asyncio.run(
            repo.create(
                owner_user_id=PydanticObjectId(),
                profile=profile_create(
                    crop_history=[
                        {
                            "crop_key": "maize",
                            "sequence_order": 1,
                            "start_date": "2024-03-15",
                            "end_date": "2024-07-15",
                            "production_system_key": "invented-system",
                        }
                    ]
                ),
            )
        )
    assert not model.records


def test_late_context_write_cannot_overwrite_a_new_history_revision() -> None:
    repo, model = repository()
    owner = PydanticObjectId()
    farm = asyncio.run(repo.create(owner_user_id=owner, profile=profile_create()))
    old_revision = farm.revision
    new_farm = asyncio.run(
        repo.update_by_owner(
            farm_id=farm.id,
            owner_user_id=owner,
            changes=FarmUpdate.model_validate({"name": "Changed during NASA call"}),
        )
    )
    old_context = FarmEnvironmentalContextState(
        status="ready",
        period=farm.environmental_context.period,
        snapshot_id=PydanticObjectId(),
        data_status="live",
    )
    stale = asyncio.run(
        repo.set_environmental_context_by_owner(
            farm_id=farm.id,
            owner_user_id=owner,
            expected_revision=old_revision,
            context=old_context,
        )
    )

    assert stale is None
    assert new_farm.revision == old_revision + 1
    assert new_farm.environmental_context.status == "pending"
    assert model.last_update_filter == {
        "_id": farm.id,
        "owner_user_id": owner,
        "revision": old_revision,
    }


def test_late_unavailable_context_cannot_downgrade_ready_same_revision() -> None:
    repo, model = repository()
    owner = PydanticObjectId()
    farm = asyncio.run(repo.create(owner_user_id=owner, profile=profile_create()))
    period = farm.environmental_context.period
    snapshot_id = PydanticObjectId()
    ready = FarmEnvironmentalContextState(
        status="ready", period=period, snapshot_id=snapshot_id, data_status="live"
    )
    saved = asyncio.run(
        repo.set_environmental_context_by_owner(
            farm_id=farm.id,
            owner_user_id=owner,
            expected_revision=farm.revision,
            context=ready,
        )
    )
    assert saved is not None

    late_unavailable = FarmEnvironmentalContextState(
        status="unavailable", period=period, data_status="unavailable"
    )
    rejected = asyncio.run(
        repo.set_environmental_context_by_owner(
            farm_id=farm.id,
            owner_user_id=owner,
            expected_revision=farm.revision,
            context=late_unavailable,
        )
    )

    assert rejected is None
    assert farm.environmental_context["status"] == "ready"
    assert farm.environmental_context["snapshot_id"] == snapshot_id
    assert model.last_update_filter == {
        "_id": farm.id,
        "owner_user_id": owner,
        "revision": farm.revision,
        "environmental_context.status": {"$nin": ["ready", "partial"]},
    }
