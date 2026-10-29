"""FastAPI Users adapters, Argon2 password handling, and cookie-session strategy (NY-11)."""

from typing import Annotated

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import Depends
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import BaseUserManager
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.exceptions import InvalidID, InvalidPasswordException
from fastapi_users.password import PasswordHelper
from fastapi_users.schemas import BaseUserCreate
from fastapi_users_db_beanie import BeanieUserDatabase
from fastapi_users_db_beanie.access_token import BeanieAccessTokenDatabase
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings
from app.models.access_tokens import AccessToken
from app.models.users import User, normalize_email

AUTH_BACKEND_NAME = "nova-yield-cookie-session"
AUTH_COOKIE_NAME = "nova_yield_session"
AUTH_CSRF_COOKIE_NAME = "nova_yield_csrf"

_PASSWORD_HELPER = PasswordHelper(PasswordHash((Argon2Hasher(),)))


def get_user_database() -> BeanieUserDatabase[User]:
    """Create a lightweight adapter over the registered Beanie User document."""

    return BeanieUserDatabase(User)


def get_access_token_database() -> BeanieAccessTokenDatabase[AccessToken]:
    """Create a lightweight adapter over the registered access-token document."""

    return BeanieAccessTokenDatabase(AccessToken)


class UserManager(BaseUserManager[User, PydanticObjectId]):
    """Use the selected Argon2 helper and canonical email for user lookups."""

    def __init__(self, user_database: BeanieUserDatabase[User]) -> None:
        super().__init__(user_database, password_helper=_PASSWORD_HELPER)

    def parse_id(self, value: object) -> PydanticObjectId:
        """Convert token document IDs to Beanie's ObjectId type for user lookup."""

        try:
            return PydanticObjectId(value)
        except (InvalidId, TypeError, ValueError) as error:
            raise InvalidID() from error

    async def get_by_email(self, user_email: str) -> User:
        """Normalize lookup input so registration and login use the stored email form."""

        return await super().get_by_email(normalize_email(user_email))

    async def authenticate_email_password(
        self,
        *,
        email: str,
        password: str,
    ) -> User | None:
        """Adapt NovaYield's email JSON contract to FastAPI Users' credential verifier."""

        library_credentials = OAuth2PasswordRequestForm(
            username=normalize_email(email),
            password=password,
        )
        return await super().authenticate(library_credentials)

    async def validate_password(self, password: str, user: BaseUserCreate | User) -> None:
        """Enforce a modest password length range before hashing or storage."""

        if not 8 <= len(password) <= 128:
            raise InvalidPasswordException(reason="Password must be between 8 and 128 characters.")


def get_user_manager(
    user_database: Annotated[BeanieUserDatabase[User], Depends(get_user_database)],
) -> UserManager:
    """Provide a request-scoped manager to FastAPI Users dependencies and routers."""

    return UserManager(user_database)


def create_cookie_auth_backend(
    settings: Settings,
) -> AuthenticationBackend[User, PydanticObjectId]:
    """Build cookie transport and database token strategy from app-specific settings."""

    cookie_transport = CookieTransport(
        cookie_name=AUTH_COOKIE_NAME,
        cookie_max_age=settings.auth_session_lifetime_seconds,
        cookie_secure=settings.auth_cookie_secure,
        cookie_httponly=True,
        cookie_samesite="lax",
    )

    def get_database_strategy(
        access_token_database: Annotated[
            BeanieAccessTokenDatabase[AccessToken], Depends(get_access_token_database)
        ],
    ) -> DatabaseStrategy:
        return DatabaseStrategy(
            database=access_token_database,
            lifetime_seconds=settings.auth_session_lifetime_seconds,
        )

    return AuthenticationBackend(
        name=AUTH_BACKEND_NAME,
        transport=cookie_transport,
        get_strategy=get_database_strategy,
    )
