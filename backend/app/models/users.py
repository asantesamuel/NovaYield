"""Authentication user document and normalized email convention (NY-11)."""

from datetime import UTC, datetime

from fastapi_users_db_beanie import BeanieBaseUserDocument
from pydantic import Field, field_validator

from app.database.registry import register_document_model

USER_COLLECTION_NAME = "users"


def normalize_email(value: str) -> str:
    """Return the canonical stored form for an email address."""

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Email cannot be empty")
    return normalized


@register_document_model
class User(BeanieBaseUserDocument):
    """FastAPI Users identity record; password hash and library flags stay internal."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_before_storage(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_email(value)
        return value

    class Settings(BeanieBaseUserDocument.Settings):
        name = USER_COLLECTION_NAME
