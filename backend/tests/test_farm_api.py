"""HTTP tests for the supported-location lookup and authenticated farm routes."""

from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Any

import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.farms.location_catalog import SUPPORTED_LOCATION_SEEDS
from app.farms.routes import (
    create_farm_router,
    get_farm_repository,
    get_supported_location_repository,
)
from app.main import create_app
from app.models.access_tokens import AccessToken
from app.models.farms import Farm
from app.models.supported_locations import SupportedLocation
from app.models.users import User
from app.repositories.farms import UnsupportedFarmLocation
from app.repositories.supported_locations import SupportedLocationRepository
from app.schemas.farms import FarmCreate, FarmUpdate
from app.services.authentication import (
    AUTH_CSRF_COOKIE_NAME,
    get_access_token_database,
    get_user_database,
)

FRONTEND_ORIGIN = "http://localhost:5173"
TEST_CSRF_SECRET = token_urlsafe(32)
TEST_PASSWORD = "safe-passphrase-123"


class FakeMongoConnection:
    async def connect(self) -> bool:
        return True

    async def is_ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class InMemoryUserDatabase:
    def __init__(self) -> None:
        self.users: dict[PydanticObjectId, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def create(self, data: dict[str, Any]) -> User:
        user = User(id=PydanticObjectId(), **data)
        self.users[user.id] = user
        return user

    async def get(self, user_id: PydanticObjectId) -> User | None:
        return self.users.get(user_id)

    async def update(self, user: User, data: dict[str, Any]) -> User:
        updated_user = user.model_copy(update=data)
        self.users[updated_user.id] = updated_user
        return updated_user

    async def delete(self, user: User) -> None:
        self.users.pop(user.id, None)


class InMemoryAccessTokenDatabase:
    def __init__(self) -> None:
        self.tokens: dict[str, AccessToken] = {}

    async def create(self, data: dict[str, Any]) -> AccessToken:
        access_token = AccessToken(**data)
        self.tokens[access_token.token] = access_token
        return access_token

    async def get_by_token(
        self,
        token: str,
        max_age: datetime | None = None,
    ) -> AccessToken | None:
        access_token = self.tokens.get(token)
        if access_token is None:
            return None
        if max_age is not None and access_token.created_at < max_age:
            return None
        return access_token

    async def delete(self, access_token: AccessToken) -> None:
        self.tokens.pop(access_token.token, None)


class InMemoryFarmRepository:
    def __init__(self, locations: SupportedLocationRepository) -> None:
        self.locations = locations
        self.farms: dict[PydanticObjectId, Farm] = {}

    async def create(self, *, owner_user_id: PydanticObjectId, profile: FarmCreate) -> Farm:
        if await self.locations.get_selectable(profile.location_key) is None:
            raise UnsupportedFarmLocation()
        now = datetime.now(UTC)
        farm = Farm.model_construct(
            id=PydanticObjectId(),
            owner_user_id=owner_user_id,
            **profile.model_dump(),
            created_at=now,
            updated_at=now,
        )
        self.farms[farm.id] = farm
        return farm

    async def list_by_owner(self, *, owner_user_id: PydanticObjectId) -> list[Farm]:
        return [farm for farm in self.farms.values() if farm.owner_user_id == owner_user_id]

    async def get_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
    ) -> Farm | None:
        farm = self.farms.get(farm_id)
        if farm is None or farm.owner_user_id != owner_user_id:
            return None
        return farm

    async def update_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        changes: FarmUpdate,
    ) -> Farm | None:
        existing = await self.get_by_owner(farm_id=farm_id, owner_user_id=owner_user_id)
        if existing is None:
            return None
        values = changes.model_dump(exclude_unset=True)
        if "location_key" in values:
            if await self.locations.get_selectable(values["location_key"]) is None:
                raise UnsupportedFarmLocation()
        updated = existing.model_copy(update={**values, "updated_at": datetime.now(UTC)})
        self.farms[farm_id] = updated
        return updated


class InMemorySupportedLocationRepository(SupportedLocationRepository):
    def __init__(self) -> None:
        self.records = [
            SupportedLocation.model_construct(**seed.model_dump())
            for seed in SUPPORTED_LOCATION_SEEDS
        ]

    async def list_selectable(self) -> list[SupportedLocation]:
        return sorted(
            (location for location in self.records if location.is_selectable),
            key=lambda location: location.sort_order,
        )

    async def get_selectable(self, location_key: str) -> SupportedLocation | None:
        return next(
            (
                location
                for location in self.records
                if location.location_key == location_key and location.is_selectable
            ),
            None,
        )

    async def get_by_key(self, location_key: str) -> SupportedLocation | None:
        return next(
            (location for location in self.records if location.location_key == location_key),
            None,
        )

    async def list_by_keys(self, location_keys: set[str]) -> list[SupportedLocation]:
        return [location for location in self.records if location.location_key in location_keys]


@pytest.fixture
def farm_api_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build isolated API clients with real auth and in-memory feature repositories."""

    monkeypatch.setattr(User, "get_pymongo_collection", lambda _self: None)
    monkeypatch.setattr(AccessToken, "get_pymongo_collection", lambda _self: None)
    user_database = InMemoryUserDatabase()
    token_database = InMemoryAccessTokenDatabase()
    location_repository = InMemorySupportedLocationRepository()
    farm_repository = InMemoryFarmRepository(location_repository)
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_cookie_secure=False,
        cors_allowed_origins=FRONTEND_ORIGIN,
        csrf_secret=SecretStr(TEST_CSRF_SECRET),
    )

    def client() -> TestClient:
        app = create_app(
            settings,
            mongo_connection_factory=lambda _settings: FakeMongoConnection(),
        )
        app.include_router(
            create_farm_router(app.state.current_active_user),
            prefix=settings.api_v1_prefix,
        )
        app.dependency_overrides[get_user_database] = lambda: user_database
        app.dependency_overrides[get_access_token_database] = lambda: token_database
        app.dependency_overrides[get_farm_repository] = lambda: farm_repository
        app.dependency_overrides[get_supported_location_repository] = lambda: location_repository
        return TestClient(app)

    return client, farm_repository, user_database


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get(
        "/api/v1/auth/csrf",
        headers={"Origin": FRONTEND_ORIGIN},
    )
    assert response.status_code == 204
    token = client.cookies.get(AUTH_CSRF_COOKIE_NAME)
    assert token is not None
    return {"Origin": FRONTEND_ORIGIN, "X-CSRF-Token": token}


def register_and_login(client: TestClient, email: str) -> dict[str, str]:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers=csrf_headers(client),
    )
    assert login.status_code == 204
    return registration.json()


def test_public_location_lookup_returns_labels_and_coverage_notice_only(
    farm_api_factory: Any,
) -> None:
    make_client, _farms, _users = farm_api_factory
    with make_client() as client:
        response = client.get("/api/v1/farms/locations")

    assert response.status_code == 200
    body = response.json()
    assert "not yet expanded to other parts of Ghana" in body["coverage_notice"]
    assert body["locations"] == [
        {"location_key": "ejura", "label": "Ejura"},
        {"location_key": "anyinasu", "label": "Anyinasu"},
        {"location_key": "kintampo", "label": "Kintampo"},
    ]
    assert "latitude" not in response.text
    assert "longitude" not in response.text
    assert "coordinates" not in response.text


def test_authenticated_user_can_create_list_get_and_update_farms(farm_api_factory: Any) -> None:
    make_client, farms, _users = farm_api_factory
    with make_client() as client:
        user = register_and_login(client, "farmer@example.com")
        created = client.post(
            "/api/v1/farms",
            json={
                "name": "North field",
                "location_key": "ejura",
                "soil_texture": "sandy loam",
            },
            headers=csrf_headers(client),
        )
        assert created.status_code == 201
        farm_body = created.json()
        farm_id = farm_body["id"]

        assert farm_body["location"] == {"location_key": "ejura", "label": "Ejura"}
        assert farm_body["soil_texture"] == "sandy loam"
        assert "owner_user_id" not in farm_body
        assert "latitude" not in created.text
        assert farms.farms[PydanticObjectId(farm_id)].owner_user_id == PydanticObjectId(user["id"])

        listed = client.get("/api/v1/farms")
        retrieved = client.get(f"/api/v1/farms/{farm_id}")
        updated = client.patch(
            f"/api/v1/farms/{farm_id}",
            json={"name": "South field", "location_key": "kintampo"},
            headers=csrf_headers(client),
        )

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert retrieved.status_code == 200
    assert retrieved.json()["name"] == "North field"
    assert updated.status_code == 200
    assert updated.json()["name"] == "South field"
    assert updated.json()["location"] == {"location_key": "kintampo", "label": "Kintampo"}
    assert "longitude" not in listed.text + retrieved.text + updated.text


def test_farm_routes_require_auth_and_reject_bad_or_unavailable_locations(
    farm_api_factory: Any,
) -> None:
    make_client, _farms, _users = farm_api_factory
    with make_client() as client:
        anonymous_list = client.get("/api/v1/farms")
        anonymous_create = client.post(
            "/api/v1/farms",
            json={"name": "North field", "location_key": "ejura"},
            headers=csrf_headers(client),
        )
        assert anonymous_list.status_code == 401
        assert anonymous_create.status_code == 401

        register_and_login(client, "farmer@example.com")
        incomplete = client.post(
            "/api/v1/farms",
            json={"location_key": "ejura"},
            headers=csrf_headers(client),
        )
        unknown_location = client.post(
            "/api/v1/farms",
            json={"name": "North field", "location_key": "unsupported-place"},
            headers=csrf_headers(client),
        )
        client_supplied_owner = client.post(
            "/api/v1/farms",
            json={
                "name": "North field",
                "location_key": "ejura",
                "owner_user_id": str(PydanticObjectId()),
            },
            headers=csrf_headers(client),
        )
        client_supplied_coordinates = client.post(
            "/api/v1/farms",
            json={
                "name": "North field",
                "location_key": "ejura",
                "latitude": 7.3856,
                "longitude": -1.3562,
            },
            headers=csrf_headers(client),
        )
        missing_csrf = client.post(
            "/api/v1/farms",
            json={"name": "No CSRF", "location_key": "ejura"},
        )

    assert incomplete.status_code == 422
    assert unknown_location.status_code == 422
    assert unknown_location.json()["detail"] == (
        "Select a location from the supported locations list."
    )
    assert client_supplied_owner.status_code == 422
    assert client_supplied_coordinates.status_code == 422
    assert "7.3856" not in client_supplied_coordinates.text
    assert "-1.3562" not in client_supplied_coordinates.text
    assert all("input" not in error for error in client_supplied_coordinates.json()["detail"])
    assert missing_csrf.status_code == 403


def test_cross_user_farm_ids_are_hidden_for_get_and_update(farm_api_factory: Any) -> None:
    make_client, _farms, _users = farm_api_factory
    with make_client() as owner_client, make_client() as other_client:
        register_and_login(owner_client, "owner@example.com")
        register_and_login(other_client, "other@example.com")
        created = owner_client.post(
            "/api/v1/farms",
            json={"name": "Owner field", "location_key": "ejura"},
            headers=csrf_headers(owner_client),
        )
        assert created.status_code == 201
        farm_id = created.json()["id"]

        foreign_get = other_client.get(f"/api/v1/farms/{farm_id}")
        foreign_update = other_client.patch(
            f"/api/v1/farms/{farm_id}",
            json={"name": "Stolen field"},
            headers=csrf_headers(other_client),
        )
        actual_owner_read = owner_client.get(f"/api/v1/farms/{farm_id}")

    assert foreign_get.status_code == 404
    assert foreign_update.status_code == 404
    assert foreign_get.json() == foreign_update.json()
    assert actual_owner_read.status_code == 200
    assert actual_owner_read.json()["name"] == "Owner field"
