"""Persistence-contract tests for NY-11 user and access-token documents."""

from datetime import UTC

import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from app.database.registry import load_document_models
from app.models.access_tokens import ACCESS_TOKEN_COLLECTION_NAME, AccessToken
from app.models.users import USER_COLLECTION_NAME, User, normalize_email


@pytest.fixture
def allow_document_construction_without_beanie_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skip collection lookup while testing Pydantic validation, not MongoDB I/O."""

    monkeypatch.setattr(User, "get_pymongo_collection", lambda _self: None)
    monkeypatch.setattr(AccessToken, "get_pymongo_collection", lambda _self: None)


def test_email_is_trimmed_and_lowercased_before_storage(
    allow_document_construction_without_beanie_initialization: None,
) -> None:
    user = User(email="  Farmer.Example@Mail.COM  ", hashed_password="argon-hash")

    assert normalize_email("  Farmer.Example@Mail.COM  ") == "farmer.example@mail.com"
    assert user.email == "farmer.example@mail.com"


def test_blank_normalized_email_is_rejected(
    allow_document_construction_without_beanie_initialization: None,
) -> None:
    with pytest.raises(ValidationError, match="Email cannot be empty"):
        User(email="  ", hashed_password="argon-hash")


def test_user_keeps_adapter_unique_case_insensitive_email_index() -> None:
    email_index = next(
        index
        for index in User.Settings.indexes
        if index.document.get("name") == "case_insensitive_email_index"
    )

    assert User.Settings.name == USER_COLLECTION_NAME
    assert email_index.document["unique"] is True
    assert email_index.document["key"] == {"email": 1}
    assert email_index.document["collation"]["strength"] == 2


def test_user_timestamps_are_created_in_utc(
    allow_document_construction_without_beanie_initialization: None,
) -> None:
    user = User(email="farmer@example.com", hashed_password="argon-hash")

    assert user.created_at.utcoffset() == UTC.utcoffset(user.created_at)
    assert user.updated_at.utcoffset() == UTC.utcoffset(user.updated_at)


def test_access_token_references_user_with_object_id_and_has_unique_token_index(
    allow_document_construction_without_beanie_initialization: None,
) -> None:
    owner_id = PydanticObjectId()
    token = AccessToken(token="opaque-test-token", user_id=owner_id)
    token_index = next(
        index for index in AccessToken.Settings.indexes if "token" in index.document.get("key", {})
    )

    assert AccessToken.Settings.name == ACCESS_TOKEN_COLLECTION_NAME
    assert token.user_id == owner_id
    assert isinstance(token.user_id, PydanticObjectId)
    assert token_index.document["unique"] is True
    assert token.created_at.tzinfo is not None


def test_auth_documents_are_discovered_by_the_shared_registry() -> None:
    document_models = load_document_models()

    assert User in document_models
    assert AccessToken in document_models
