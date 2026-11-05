"""Explicitly label pre-v2 farms as unresolved, without inventing crop dates."""

import asyncio

from app.core.config import get_settings
from app.database.connection import MongoConnection
from app.repositories.farms import FarmRepository


async def mark_legacy_farms() -> int:
    connection = MongoConnection(get_settings())
    try:
        if not await connection.connect():
            raise RuntimeError("MongoDB is unavailable; legacy migration did not run")
        return await FarmRepository().mark_legacy_unresolved()
    finally:
        await connection.close()


def main() -> None:
    count = asyncio.run(mark_legacy_farms())
    print(f"Marked {count} legacy farm(s) as unresolved; no history dates were inferred.")


if __name__ == "__main__":
    main()
