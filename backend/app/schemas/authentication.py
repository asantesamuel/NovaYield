"""Authentication request and response schemas (NY-11)."""

from beanie import PydanticObjectId
from fastapi_users.schemas import BaseUser
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.models.users import normalize_email


class EmailPasswordRequest(BaseModel):
    """Share the public JSON credential contract used by registration and login."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr

    @field_validator("email", mode="before")
    @classmethod
    def canonicalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_email(value)
        return value


class RegistrationRequest(EmailPasswordRequest):
    """Accept email and password when creating an account."""


class LoginRequest(EmailPasswordRequest):
    """Accept email and password when creating an authenticated session."""


class PublicUser(BaseUser[PydanticObjectId]):
    """Expose account identity without password hashes or internal capability flags."""

    is_active: bool = Field(default=True, exclude=True)
    is_superuser: bool = Field(default=False, exclude=True)
    is_verified: bool = Field(default=False, exclude=True)
