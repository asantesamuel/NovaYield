"""FastAPI dependencies for reusing the app's MongoDB connection boundary."""

from typing import Any

from fastapi import Request

from app.database.connection import MongoConnection


def get_mongo_connection(request: Request) -> MongoConnection:
    """Return the MongoDB connection created once by the application lifespan."""

    return request.app.state.mongo


def get_mongo_database(request: Request) -> Any:
    """Return the selected database for features using lower-level PyMongo APIs."""

    return get_mongo_connection(request).database
