"""MongoDB persistence operations for owner-scoped farm profiles (NY-19)."""

from datetime import UTC, datetime
from typing import Any, cast

from beanie import PydanticObjectId, UpdateResponse

from app.models.farms import Farm
from app.models.supported_locations import SupportedLocation
from app.schemas.farms import FarmCreate, FarmUpdate


class UnsupportedFarmLocation(ValueError):
    """Raised when a farm references a missing or non-selectable catalog entry."""

    def __init__(self) -> None:
        super().__init__("Choose a location from the supported-location catalog")


class FarmRepository:
    """Keep ownership and supported-location checks inside MongoDB operations."""

    def __init__(
        self,
        farm_model: Any = Farm,
        supported_location_model: Any = SupportedLocation,
    ) -> None:
        """Allow model doubles in unit tests; production uses the Beanie documents."""

        self._farm_model = farm_model
        self._supported_location_model = supported_location_model

    async def create(self, *, owner_user_id: PydanticObjectId, profile: FarmCreate) -> Farm:
        """Persist a validated profile with owner supplied by the authenticated caller."""

        await self._require_selectable_location(profile.location_key)
        farm = self._farm_model(owner_user_id=owner_user_id, **profile.model_dump())
        await farm.insert()
        return farm

    async def list_by_owner(self, *, owner_user_id: PydanticObjectId) -> list[Farm]:
        """Return only farms whose stored owner matches the authenticated user."""

        return await self._farm_model.find({"owner_user_id": owner_user_id}).to_list()

    async def get_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
    ) -> Farm | None:
        """Fetch by both document ID and owner so foreign IDs do not disclose data."""

        return await self._farm_model.find_one({"_id": farm_id, "owner_user_id": owner_user_id})

    async def update_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        changes: FarmUpdate,
    ) -> Farm | None:
        """Atomically update only an owned farm and validate a changed catalog key."""

        update_values = changes.model_dump(exclude_unset=True)
        if "location_key" in update_values:
            await self._require_selectable_location(update_values["location_key"])
        update_values["updated_at"] = datetime.now(UTC)
        result = await self._farm_model.find_one(
            {"_id": farm_id, "owner_user_id": owner_user_id}
        ).update(
            {"$set": update_values},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )
        return cast(Farm | None, result)

    async def _require_selectable_location(self, location_key: str) -> None:
        location = await self._supported_location_model.find_one(
            {"location_key": location_key, "is_selectable": True}
        )
        if location is None:
            raise UnsupportedFarmLocation()
