"""Owner-scoped Farm v2 writes with canonical catalog-reference validation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from beanie import PydanticObjectId, UpdateResponse

from app.farms.context_window import derive_context_period
from app.models.farms import (
    FARM_V1_SCHEMA_VERSION,
    FARM_V2_SCHEMA_VERSION,
    CropHistoryEvent,
    Farm,
    FarmEnvironmentalContextState,
    HistoryGap,
)
from app.models.supported_locations import SupportedLocation
from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.farm_reference_options import FarmReferenceRepository
from app.schemas.farms import (
    CropHistoryEventInput,
    FarmCreate,
    FarmUpdate,
)


class UnsupportedFarmLocation(ValueError):
    def __init__(self) -> None:
        super().__init__("Choose a location from the supported-location catalog")


class UnsupportedFarmReference(ValueError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"Choose an active {kind} option from the farm reference catalog")


class UnsupportedHistoryCrop(ValueError):
    def __init__(self) -> None:
        super().__init__("Choose an active crop from the history crop catalog")


class UnsupportedCropProfile(ValueError):
    def __init__(self) -> None:
        super().__init__("Choose a listed variety and production-system scope or leave it unknown")


class IncompleteFarmMigration(ValueError):
    def __init__(self) -> None:
        super().__init__(
            "A legacy farm needs new catalog choices and dated crop history before v2 use"
        )


class FarmRevisionConflict(ValueError):
    """A concurrent edit changed the Farm after this PATCH loaded its inputs."""

    def __init__(self) -> None:
        super().__init__("The farm changed while it was being edited. Reload and retry.")


class FarmRepository:
    """All Farm ID reads and writes include the authenticated owner reference."""

    def __init__(
        self,
        farm_model: Any = Farm,
        supported_location_model: Any = SupportedLocation,
        crop_repository: CropCatalogRepository | None = None,
        reference_repository: FarmReferenceRepository | None = None,
    ) -> None:
        self._farm_model = farm_model
        self._supported_location_model = supported_location_model
        self._crops = crop_repository or CropCatalogRepository()
        self._references = reference_repository or FarmReferenceRepository()

    async def create(self, *, owner_user_id: PydanticObjectId, profile: FarmCreate) -> Farm:
        """Save an owned Farm before any NASA request; no caller-supplied owner ID."""

        await self._require_selectable_location(profile.location_key)
        await self._require_references(profile.soil_texture_key, profile.irrigation_access_key)
        events = await self._resolve_history(profile.crop_history)
        period = derive_context_period(events) if profile.history_status == "complete" else None
        context = FarmEnvironmentalContextState(
            status="pending" if period is not None else "needs_review",
            period=period,
            warning_code=None if period is not None else "HISTORY_NEEDS_REVIEW",
        )
        profile_values = profile.model_dump(exclude={"crop_history", "declared_gaps"})
        farm = self._farm_model(
            owner_user_id=owner_user_id,
            schema_version=FARM_V2_SCHEMA_VERSION,
            revision=1,
            **profile_values,
            crop_history=events,
            declared_gaps=[
                HistoryGap.model_validate(gap.model_dump()) for gap in profile.declared_gaps
            ],
            soil_texture_source=(
                "unknown" if profile.soil_texture_key == "unknown" else "farmer_reported"
            ),
            environmental_context=context,
        )
        await farm.insert()
        return farm

    async def list_by_owner(self, *, owner_user_id: PydanticObjectId) -> list[Farm]:
        return await self._farm_model.find({"owner_user_id": owner_user_id}).to_list()

    async def get_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
    ) -> Farm | None:
        return await self._farm_model.find_one({"_id": farm_id, "owner_user_id": owner_user_id})

    async def update_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        changes: FarmUpdate,
    ) -> Farm | None:
        """Validate the merged PATCH and CAS the owner-scoped input revision."""

        existing = await self.get_by_owner(farm_id=farm_id, owner_user_id=owner_user_id)
        if existing is None:
            return None
        incoming = changes.model_dump(exclude_unset=True)
        if "location_key" in incoming:
            await self._require_selectable_location(incoming["location_key"])
        if "soil_texture_key" in incoming or "irrigation_access_key" in incoming:
            await self._require_references(
                incoming.get("soil_texture_key", existing.soil_texture_key),
                incoming.get("irrigation_access_key", existing.irrigation_access_key),
            )

        v2_fields = {
            "soil_texture_key",
            "irrigation_access_key",
            "history_status",
            "crop_history",
            "declared_gaps",
            "current_plot_available",
            "earliest_available_date",
        }
        migrating_or_replacing = bool(v2_fields.intersection(incoming))
        update_values: dict[str, Any]
        if existing.schema_version == FARM_V2_SCHEMA_VERSION or migrating_or_replacing:
            if existing.schema_version == FARM_V2_SCHEMA_VERSION:
                merged = _existing_v2_input(existing)
                merged.update(incoming)
            else:
                required = {"soil_texture_key", "irrigation_access_key", "history_status"}
                if not required.issubset(incoming):
                    raise IncompleteFarmMigration()
                merged = {"name": existing.name, "location_key": existing.location_key}
                merged.update(incoming)
            profile = FarmCreate.model_validate(merged)
            await self._require_references(profile.soil_texture_key, profile.irrigation_access_key)
            events = await self._resolve_history(
                profile.crop_history,
                existing_events=existing.crop_history,
            )
            period = derive_context_period(events) if profile.history_status == "complete" else None
            context_changed = (
                existing.schema_version != FARM_V2_SCHEMA_VERSION
                or "crop_history" in incoming
                or "history_status" in incoming
                or "location_key" in incoming
            )
            update_values = profile.model_dump(exclude={"crop_history", "declared_gaps"})
            update_values.update(
                schema_version=FARM_V2_SCHEMA_VERSION,
                crop_history=[event.model_dump() for event in events],
                declared_gaps=(
                    [
                        HistoryGap.model_validate(gap.model_dump()).model_dump()
                        for gap in profile.declared_gaps
                    ]
                    if (
                        "declared_gaps" in incoming
                        or existing.schema_version != FARM_V2_SCHEMA_VERSION
                    )
                    else [gap.model_dump() for gap in existing.declared_gaps]
                ),
                soil_texture_source=(
                    "unknown" if profile.soil_texture_key == "unknown" else "farmer_reported"
                ),
            )
            if context_changed:
                update_values["environmental_context"] = FarmEnvironmentalContextState(
                    status="pending" if period is not None else "needs_review",
                    period=period,
                    warning_code=None if period is not None else "HISTORY_NEEDS_REVIEW",
                ).model_dump()
        else:
            # Existing v1 records stay v1 until the owner supplies new catalog
            # references and actual dates. A name-only edit cannot infer history.
            update_values = incoming

        update_values["updated_at"] = datetime.now(UTC)
        update_filter: dict[str, Any] = {
            "_id": farm_id,
            "owner_user_id": owner_user_id,
            "revision": existing.revision,
        }
        if existing.schema_version == FARM_V1_SCHEMA_VERSION and existing.revision == 0:
            # A pre-migration legacy document may still lack the revision key.
            update_filter.pop("revision")
            update_filter["$or"] = [
                {"revision": 0},
                {"revision": {"$exists": False}},
            ]
        result = await self._farm_model.find_one(update_filter).update(
            {"$set": update_values, "$inc": {"revision": 1}},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )
        if result is None:
            raise FarmRevisionConflict()
        return cast(Farm, result)

    async def set_environmental_context_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        expected_revision: int,
        context: FarmEnvironmentalContextState,
    ) -> Farm | None:
        """CAS the snapshot link for the exact user-input revision that was queried.

        Every input/history/location PATCH increments revision, so an old NASA
        response cannot attach its snapshot to changed inputs. Farm.updated_at
        marks user edits; context.updated_at marks this derived-data refresh.
        An unavailable outcome also cannot downgrade same-revision usable data.
        """

        update_filter: dict[str, Any] = {
            "_id": farm_id,
            "owner_user_id": owner_user_id,
            "revision": expected_revision,
        }
        if context.status == "unavailable":
            # Two workers can retrieve the same input revision concurrently.
            # A late failed/lease-contending request must not replace another
            # worker's already usable snapshot link with an unavailable state.
            update_filter["environmental_context.status"] = {"$nin": ["ready", "partial"]}
        result = await self._farm_model.find_one(update_filter).update(
            {"$set": {"environmental_context": context.model_dump()}},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )
        return cast(Farm | None, result)

    async def mark_legacy_unresolved(self) -> int:
        """Backfill only an explicit v1 state, without translating old text."""

        collection = self._farm_model.get_pymongo_collection()
        result = await collection.update_many(
            {"schema_version": {"$exists": False}, "crop_history": {"$exists": False}},
            {
                "$set": {
                    "schema_version": FARM_V1_SCHEMA_VERSION,
                    "history_status": "legacy_unresolved",
                    "revision": 0,
                }
            },
        )
        return result.modified_count

    async def _resolve_history(
        self,
        events: list[CropHistoryEventInput],
        *,
        existing_events: list[CropHistoryEvent] | None = None,
    ) -> list[CropHistoryEvent]:
        existing_by_signature = {
            _history_signature(
                event.crop_key_snapshot,
                event.sequence_order,
                event.start_date,
                event.end_date,
                event.variety_key,
                event.production_system_key,
            ): event.event_id
            for event in existing_events or []
        }
        existing_by_order_crop = {
            (event.sequence_order, event.crop_key_snapshot): event
            for event in existing_events or []
        }
        resolved: list[CropHistoryEvent] = []
        for event in events:
            old_event = existing_by_order_crop.get((event.sequence_order, event.crop_key))
            if old_event is None:
                crop = await self._crops.get_history_crop(event.crop_key)
                if crop is None or crop.id is None:
                    raise UnsupportedHistoryCrop()
                crop_id, crop_key = crop.id, crop.crop_key
            else:
                # A retained inactive crop remains a truthful historical ID.
                # Deactivation blocks *new* selection, not editing an existing
                # event's dates or unrelated farm fields.
                crop_id, crop_key = old_event.crop_id, old_event.crop_key_snapshot
            # A supplied variety/system is a scoped catalog reference, not a
            # free-text trait source. Unknown context remains null.
            scope_changed = old_event is None or (
                old_event.variety_key != event.variety_key
                or old_event.production_system_key != event.production_system_key
            )
            if scope_changed and (
                event.variety_key is not None or event.production_system_key is not None
            ):
                profile = await self._crops.get_active_profile(
                    crop_id,
                    variety_key=event.variety_key,
                    production_system_key=event.production_system_key,
                )
                if profile is None:
                    raise UnsupportedCropProfile()
            signature = _history_signature(
                event.crop_key,
                event.sequence_order,
                event.start_date,
                event.end_date,
                event.variety_key,
                event.production_system_key,
            )
            resolved.append(
                CropHistoryEvent(
                    event_id=existing_by_signature.get(signature, str(uuid4())),
                    crop_id=crop_id,
                    crop_key_snapshot=crop_key,
                    sequence_order=event.sequence_order,
                    start_date=event.start_date,
                    end_date=event.end_date,
                    variety_key=event.variety_key,
                    production_system_key=event.production_system_key,
                    date_precision=(
                        "day"
                        if event.start_date is not None and event.end_date is not None
                        else "unknown"
                    ),
                )
            )
        return resolved

    async def _require_selectable_location(self, location_key: str) -> None:
        location = await self._supported_location_model.find_one(
            {"location_key": location_key, "is_selectable": True}
        )
        if location is None:
            raise UnsupportedFarmLocation()

    async def _require_references(
        self, soil_texture_key: str | None, irrigation_access_key: str | None
    ) -> None:
        if (
            soil_texture_key is None
            or await self._references.get_selectable("soil_texture", soil_texture_key) is None
        ):
            raise UnsupportedFarmReference("soil texture")
        if (
            irrigation_access_key is None
            or await self._references.get_selectable("irrigation_access", irrigation_access_key)
            is None
        ):
            raise UnsupportedFarmReference("irrigation access")


def _history_signature(
    crop_key: str,
    sequence_order: int,
    start_date: Any,
    end_date: Any,
    variety_key: str | None,
    production_system_key: str | None,
) -> tuple[Any, ...]:
    return (crop_key, sequence_order, start_date, end_date, variety_key, production_system_key)


def _existing_v2_input(farm: Farm) -> dict[str, Any]:
    return {
        "name": farm.name,
        "location_key": farm.location_key,
        "soil_texture_key": farm.soil_texture_key,
        "irrigation_access_key": farm.irrigation_access_key,
        "history_status": farm.history_status,
        "crop_history": [
            dict(
                crop_key=event.crop_key_snapshot,
                sequence_order=event.sequence_order,
                start_date=event.start_date,
                end_date=event.end_date,
                variety_key=event.variety_key,
                production_system_key=event.production_system_key,
            )
            for event in farm.crop_history
        ],
        "declared_gaps": [
            dict(
                start_date=gap.start_date,
                end_date=gap.end_date,
                status=gap.status,
                source="farmer_reported",
            )
            for gap in farm.declared_gaps
        ],
        "current_plot_available": farm.current_plot_available,
        "earliest_available_date": farm.earliest_available_date,
        "farmer_priorities": farm.farmer_priorities,
    }
