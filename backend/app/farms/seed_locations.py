"""Seed the initial supported-location catalog into the configured MongoDB."""

import asyncio

from app.core.config import get_settings
from app.database.connection import MongoConnection
from app.repositories.supported_locations import SupportedLocationRepository


async def seed_supported_locations() -> tuple[int, tuple[str, ...]]:
    """Insert absent records and read back safe keys/labels to verify the catalog."""

    connection = MongoConnection(get_settings())
    try:
        if not await connection.connect():
            raise RuntimeError("MongoDB is unavailable; supported locations were not seeded")
        repository = SupportedLocationRepository()
        inserted = await repository.seed_missing()
        locations = await repository.list_selectable()
        return inserted, tuple(
            f"{location.location_key}: {location.label}" for location in locations
        )
    finally:
        await connection.close()


def main() -> None:
    inserted, locations = asyncio.run(seed_supported_locations())
    labels = ", ".join(locations)
    print(f"Supported-location catalog ready; inserted {inserted} new record(s).")
    print(f"Selectable locations: {labels}")


if __name__ == "__main__":
    main()
