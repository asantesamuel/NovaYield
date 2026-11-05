"""Read and seed the curated, coordinate-private location catalog."""

from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.farms.contracts import SupportedLocationSeed
from app.farms.location_catalog import SUPPORTED_LOCATION_SEEDS
from app.models.supported_locations import SupportedLocation


class SupportedLocationRepository:
    """Persist catalog points and provide only selectable records to features."""

    def __init__(self, location_model: Any = SupportedLocation) -> None:
        """Allow a small model double in tests while production uses Beanie."""

        self._location_model = location_model

    async def list_selectable(self) -> list[SupportedLocation]:
        """Return supported locations in stable display order."""

        return (
            await self._location_model.find({"is_selectable": True})
            .sort([("sort_order", ASCENDING), ("location_key", ASCENDING)])
            .to_list()
        )

    async def get_selectable(self, location_key: str) -> SupportedLocation | None:
        """Resolve one location only if it is currently offered to users."""

        return await self._location_model.find_one(
            {"location_key": location_key, "is_selectable": True}
        )

    async def get_by_key(self, location_key: str) -> SupportedLocation | None:
        """Resolve a catalog record for an existing farm, even if no longer selectable."""

        return await self._location_model.find_one({"location_key": location_key})

    async def list_by_keys(self, location_keys: set[str]) -> list[SupportedLocation]:
        """Resolve multiple farm references in one query instead of doing an N+1 lookup."""

        if not location_keys:
            return []
        return await self._location_model.find(
            {"location_key": {"$in": sorted(location_keys)}}
        ).to_list()

    async def seed_missing(
        self,
        seeds: tuple[SupportedLocationSeed, ...] = SUPPORTED_LOCATION_SEEDS,
    ) -> int:
        """Insert catalog entries that do not exist; never overwrite reviewed records."""

        inserted = 0
        for seed in seeds:
            existing = await self._location_model.find_one({"location_key": seed.location_key})
            if existing is not None:
                continue

            location = self._location_model(**seed.model_dump())
            try:
                await location.insert()
            except DuplicateKeyError:
                # Another seed process may have inserted the unique key concurrently.
                existing = await self._location_model.find_one({"location_key": seed.location_key})
                if existing is None:
                    raise
                continue
            inserted += 1
        return inserted
