"""MongoDB persistence operations for owner-scoped farm profiles (NY-19)."""

from datetime import UTC, datetime
from typing import Any, cast

from beanie import PydanticObjectId, UpdateResponse

from app.models.farms import Farm
from app.schemas.farms import FarmCreate, FarmUpdate


class FarmRepository:
    """Keep ownership conditions inside MongoDB reads and writes."""

    def __init__(self, farm_model: Any = Farm) -> None:
        """Allow a small model double in unit tests; production uses Beanie's Farm."""

        self._farm_model = farm_model

    async def create(self, *, owner_user_id: PydanticObjectId, profile: FarmCreate) -> Farm:
        """Persist a validated profile with owner supplied by the authenticated caller."""

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
        """Atomically update only a farm matching both ID and authenticated owner."""

        update_values = changes.model_dump(exclude_unset=True)
        update_values["updated_at"] = datetime.now(UTC)
        result = await self._farm_model.find_one(
            {"_id": farm_id, "owner_user_id": owner_user_id}
        ).update(
            {"$set": update_values},
            response_type=UpdateResponse.NEW_DOCUMENT,
        )
        return cast(Farm | None, result)
