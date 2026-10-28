"""Mock-backed tests for the NY-6 snapshot repository."""

from datetime import date
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from app.integrations.nasa.power import PowerRequest
from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotSeasonContext,
    build_snapshot_identity,
)
from app.repositories.environmental_snapshots import (
    EnvironmentalSnapshotRepository,
    SnapshotIdentityConflict,
    SnapshotStorageUnavailable,
)

TEST_IDENTITY_SECRET = "repository-test-secret-value-has-at-least-32-bytes"
TEST_IDENTITY = build_snapshot_identity(
    PowerRequest(
        latitude=0.0,
        longitude=0.0,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    ),
    location_secret=TEST_IDENTITY_SECRET,
)


def run_immediately(awaitable: Any) -> Any:
    """Run repository coroutines backed only by immediate in-memory fakes."""
    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("The in-memory repository fake unexpectedly suspended.")


def make_snapshot() -> EnvironmentalSnapshot:
    return EnvironmentalSnapshot.model_construct(
        identity=TEST_IDENTITY,
        request_contexts=[],
    )


def test_lookup_uses_opaque_request_key_and_returns_persisted_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = make_snapshot()
    calls: list[tuple[dict[str, str], bool]] = []

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        calls.append((query, ignore_cache))
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))

    found = run_immediately(EnvironmentalSnapshotRepository().find_by_identity(TEST_IDENTITY))

    assert found is snapshot
    assert calls == [({"identity.request_key": TEST_IDENTITY.request_key}, True)]


def test_insert_if_absent_returns_existing_snapshot_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = make_snapshot()

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        assert ignore_cache
        return existing

    async def unexpected_insert(_snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        pytest.fail("An existing snapshot must not be inserted again.")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", unexpected_insert)

    outcome = run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(make_snapshot()))

    assert outcome.snapshot is existing
    assert outcome.inserted is False


def test_insert_if_absent_stores_snapshot_after_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = make_snapshot()
    find_calls = 0
    insert_calls = 0

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> None:
        nonlocal find_calls
        find_calls += 1
        assert ignore_cache
        return None

    async def fake_insert(snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        nonlocal insert_calls
        insert_calls += 1
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", fake_insert)

    outcome = run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(candidate))

    assert outcome.snapshot is candidate
    assert outcome.inserted is True
    assert find_calls == 1
    assert insert_calls == 1


def test_duplicate_insert_race_returns_the_winning_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = make_snapshot()
    find_calls = 0

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot | None:
        nonlocal find_calls
        find_calls += 1
        assert ignore_cache
        return None if find_calls == 1 else winner

    async def fake_insert(_snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        raise DuplicateKeyError("duplicate key details must not escape")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", fake_insert)

    outcome = run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(make_snapshot()))

    assert outcome.snapshot is winner
    assert outcome.inserted is False
    assert find_calls == 2


def test_duplicate_conflict_and_storage_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing_find(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> None:
        assert ignore_cache
        return None

    async def duplicate_insert(_snapshot: EnvironmentalSnapshot) -> None:
        raise DuplicateKeyError("raw details: mongodb://user:private-password@host")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(missing_find))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", duplicate_insert)

    with pytest.raises(SnapshotIdentityConflict) as conflict:
        run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(make_snapshot()))
    assert "private-password" not in str(conflict.value)

    async def unavailable_find(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> None:
        assert ignore_cache
        raise ServerSelectionTimeoutError("mongodb://user:private-password@host")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(unavailable_find))

    with pytest.raises(SnapshotStorageUnavailable) as unavailable:
        run_immediately(EnvironmentalSnapshotRepository().find_by_identity(TEST_IDENTITY))
    assert "private-password" not in str(unavailable.value)


def test_request_context_is_added_with_atomic_add_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = make_snapshot()
    update_calls: list[dict[str, Any]] = []

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        assert ignore_cache
        return snapshot

    async def fake_update(
        _snapshot: EnvironmentalSnapshot, update: dict[str, Any]
    ) -> EnvironmentalSnapshot:
        update_calls.append(update)
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "update", fake_update)
    context = SnapshotSeasonContext(
        season_label="major-season-v1",
        calendar_source_version="research-v1",
        crop="maize",
    )

    updated = run_immediately(
        EnvironmentalSnapshotRepository().add_request_context(TEST_IDENTITY, context)
    )

    assert updated is snapshot
    assert update_calls == [
        {
            "$addToSet": {
                "request_contexts": {
                    "season_label": "major-season-v1",
                    "calendar_source_version": "research-v1",
                    "crop": "maize",
                }
            }
        }
    ]
