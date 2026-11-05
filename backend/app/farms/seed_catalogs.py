"""Run with ``python -m app.farms.seed_catalogs`` after MongoDB is configured."""

import asyncio

from app.core.config import get_settings
from app.database.connection import MongoConnection
from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.farm_reference_options import FarmReferenceRepository


async def seed_catalogs() -> dict[str, int]:
    connection = MongoConnection(get_settings())
    try:
        if not await connection.connect():
            raise RuntimeError("MongoDB is unavailable; catalog seeding did not run")
        counts = await CropCatalogRepository().seed_missing()
        counts["reference_options"] = await FarmReferenceRepository().seed_missing()
        return counts
    finally:
        await connection.close()


def main() -> None:
    counts = asyncio.run(seed_catalogs())
    print(
        "NovaYield catalogs ready; inserted "
        + ", ".join(f"{kind}={count}" for kind, count in counts.items())
    )


if __name__ == "__main__":
    main()
