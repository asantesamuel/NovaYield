"""Registration, cookie authentication, CSRF bootstrap, and identity routes (NY-11)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi_users import FastAPIUsers
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.exceptions import InvalidPasswordException, UserAlreadyExists
from fastapi_users.schemas import BaseUserCreate
from pymongo.errors import DuplicateKeyError

from app.core.config import Settings
from app.models.users import User
from app.schemas.authentication import LoginRequest, PublicUser, RegistrationRequest
from app.services.authentication import UserManager, create_cookie_auth_backend, get_user_manager

GENERIC_REGISTRATION_ERROR = "Unable to create an account with those details."
GENERIC_LOGIN_ERROR = "LOGIN_BAD_CREDENTIALS"


@dataclass(frozen=True)
class AuthenticationComponents:
    """Per-app auth router and reusable dependency for authenticated features."""

    router: APIRouter
    current_active_user: Callable[..., User]


def create_authentication_components(settings: Settings) -> AuthenticationComponents:
    """Build auth routes using the settings and backend belonging to this app instance."""

    backend = create_cookie_auth_backend(settings)
    fastapi_users = FastAPIUsers(get_user_manager, [backend])
    current_active_user = fastapi_users.current_user(active=True)

    router = APIRouter(prefix="/auth", tags=["authentication"])
    get_current_user_token = fastapi_users.authenticator.current_user_token(active=True)

    @router.post(
        "/login",
        name=f"auth:{backend.name}.login",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        responses={status.HTTP_400_BAD_REQUEST: {"description": "Bad credentials."}},
        summary="Log in with an email and password",
    )
    async def login(
        payload: LoginRequest,
        request: Request,
        user_manager: Annotated[UserManager, Depends(get_user_manager)],
        strategy: Annotated[DatabaseStrategy, Depends(backend.get_strategy)],
    ) -> Response:
        """Verify JSON credentials and issue the library-managed cookie session."""

        user = await user_manager.authenticate_email_password(
            email=payload.email,
            password=payload.password.get_secret_value(),
        )
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GENERIC_LOGIN_ERROR,
            )

        response = await backend.login(strategy, user)
        await user_manager.on_after_login(user, request, response)
        return response

    @router.post(
        "/logout",
        name=f"auth:{backend.name}.logout",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        responses={status.HTTP_401_UNAUTHORIZED: {"description": "Missing or inactive session."}},
        summary="Log out and revoke the current session",
    )
    async def logout(
        user_token: Annotated[tuple[User, str], Depends(get_current_user_token)],
        strategy: Annotated[DatabaseStrategy, Depends(backend.get_strategy)],
    ) -> Response:
        """Revoke the authenticated database-backed session and clear its cookie."""

        user, token = user_token
        return await backend.logout(strategy, user, token)

    @router.get(
        "/csrf",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Initialize the CSRF cookie for browser requests",
    )
    async def initialize_csrf_cookie() -> Response:
        """A safe response lets CSRF middleware issue its signed, readable cookie."""

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/register",
        response_model=PublicUser,
        status_code=status.HTTP_201_CREATED,
        summary="Register an email and password account",
    )
    async def register(
        payload: RegistrationRequest,
        request: Request,
        user_manager: Annotated[UserManager, Depends(get_user_manager)],
    ) -> PublicUser:
        """Create an account and keep duplicate-email errors deliberately generic."""

        user_create = BaseUserCreate(
            email=payload.email,
            password=payload.password.get_secret_value(),
        )
        try:
            user = await user_manager.create(user_create, safe=True, request=request)
        except (UserAlreadyExists, InvalidPasswordException, DuplicateKeyError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GENERIC_REGISTRATION_ERROR,
            ) from None

        return PublicUser.model_validate(user)

    @router.get(
        "/me",
        response_model=PublicUser,
        summary="Return the authenticated user's public identity",
    )
    async def read_current_user(
        user: Annotated[User, Depends(current_active_user)],
    ) -> User:
        """Expose only the public schema for the user authenticated by the cookie."""

        return user

    return AuthenticationComponents(
        router=router,
        current_active_user=current_active_user,
    )
