"""Read and idempotently seed broad, backend-owned farm setup choices."""

from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.farms.catalog_seed_data import REFERENCE_OPTION_SEEDS
from app.models.farm_reference_options import FarmReferenceOption, ReferenceKind


class FarmReferenceRepository:
    def __init__(self, option_model: Any = FarmReferenceOption) -> None:
        self._option_model = option_model

    async def list_selectable(self, kind: ReferenceKind) -> list[FarmReferenceOption]:
        return (
            await self._option_model.find({"kind": kind, "selectable": True})
            .sort([("key", ASCENDING)])
            .to_list()
        )

    async def get_selectable(self, kind: ReferenceKind, key: str) -> FarmReferenceOption | None:
        return await self._option_model.find_one({"kind": kind, "key": key, "selectable": True})

    async def get_by_key(self, kind: ReferenceKind, key: str) -> FarmReferenceOption | None:
        return await self._option_model.find_one({"kind": kind, "key": key})

    async def seed_missing(self) -> int:
        inserted = 0
        for seed in REFERENCE_OPTION_SEEDS:
            query = {"kind": seed["kind"], "key": seed["key"]}
            if await self._option_model.find_one(query) is not None:
                continue
            option = self._option_model(**seed)
            try:
                await option.insert()
                inserted += 1
            except DuplicateKeyError:
                if await self._option_model.find_one(query) is None:
                    raise
        return inserted
