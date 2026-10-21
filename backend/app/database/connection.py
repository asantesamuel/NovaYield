"""One async MongoDB client and Beanie initialization boundary per app lifespan."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from beanie import Document, init_beanie
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.core.config import Settings
from app.database.registry import load_document_models

logger = logging.getLogger(__name__)

ClientFactory = Callable[..., AsyncMongoClient]
BeanieInitializer = Callable[..., Awaitable[None]]
DocumentModelLoader = Callable[[], tuple[type[Document], ...]]


class MongoConnection:
    """Own the shared client, database handle, Beanie initialization, and readiness probe."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: ClientFactory = AsyncMongoClient,
        beanie_initializer: BeanieInitializer = init_beanie,
        document_model_loader: DocumentModelLoader = load_document_models,
    ) -> None:
        self._client = client_factory(
            settings.mongodb_uri.get_secret_value(),
            serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
        )
        self._database = self._client[settings.mongodb_database_name]
        self._beanie_initializer = beanie_initializer
        self._document_model_loader = document_model_loader
        self._initialization_lock = asyncio.Lock()
        self._initialized = False

    @property
    def client(self) -> AsyncMongoClient:
        """The single client features may reuse for lower-level PyMongo operations."""

        return self._client

    @property
    def database(self) -> Any:
        """The configured database handle shared by repositories and integrations."""

        return self._database

    async def connect(self) -> bool:
        """Ping MongoDB and initialize Beanie once; return false when MongoDB is unavailable."""

        async with self._initialization_lock:
            if self._initialized:
                return await self._ping()
            if not await self._ping():
                return False

            try:
                await self._beanie_initializer(
                    database=self._database,
                    document_models=self._document_model_loader(),
                )
            except PyMongoError:
                self._log_unavailable()
                return False

            self._initialized = True
            return True

    async def is_ready(self) -> bool:
        """Provide a safe readiness probe and retry initialization after startup outages."""

        if not self._initialized:
            return await self.connect()
        return await self._ping()

    async def close(self) -> None:
        """Close the client when FastAPI's lifespan ends."""

        await self._client.close()
        self._initialized = False

    async def _ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
        except PyMongoError:
            self._log_unavailable()
            return False
        return True

    @staticmethod
    def _log_unavailable() -> None:
        # Never log PyMongo exceptions or the URI: driver error text can contain credentials.
        logger.warning("MongoDB is unavailable; database readiness is false.")
