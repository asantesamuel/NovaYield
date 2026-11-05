"""Persistence-boundary tests use synthetic NY-8 inputs, not recommendation evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError
from pymongo import DESCENDING

from app.database.registry import load_document_models
from app.decisions.rotation import (
    CropCandidate,
    PlantingEventSlot,
    RotationGenerationRequest,
    RotationGenerationResult,
    generate_rotation_candidates,
)
from app.decisions.scoring import (
    CRITERIA,
    CriterionEvidence,
    RotationOptionEvidence,
    ScoringRequest,
    ScoringResult,
    score_rotation_options,
)
from app.farms.contracts import default_farmer_priorities
from app.models.farms import Farm
from app.models.rotation_results import (
    ROTATION_RESULT_HISTORY_INDEX_NAME,
    ROTATION_RESULTS_COLLECTION_NAME,
    FarmDecisionInputSnapshot,
    RotationDecisionInputs,
    RotationResult,
)
from app.repositories.rotation_results import (
    FarmNotOwnedForResult,
    FarmNotPersistedForResult,
    RotationResultRepository,
)


def make_decision_artifacts() -> tuple[
    RotationDecisionInputs,
    RotationGenerationResult,
    ScoringResult,
]:
    """Create a small, explicitly synthetic generation/scoring input and output."""

    generation_request = RotationGenerationRequest(
        planting_events=(
            PlantingEventSlot(
                event_id=f"event-{order}",
                order=order,
                plot_id="synthetic-plot",
                season_label=f"synthetic-season-{order}",
                window_start=date(2024, order, 1),
                window_end=date(2024, order, 10),
            )
            for order in (1, 2, 3)
        ),
        candidate_crops=(CropCandidate(crop_id="maize", display_name="Maize"),),
    )
    generation_result = generate_rotation_candidates(generation_request)
    candidate = generation_result.candidates[0]
    scoring_request = ScoringRequest(
        options=(
            RotationOptionEvidence(
                candidate=candidate,
                criteria=tuple(
                    CriterionEvidence(
                        criterion=criterion,
                        status="not_assessed",
                        rationale="Synthetic fixture leaves this evidence unknown.",
                    )
                    for criterion in CRITERIA
                ),
                assumptions=("Synthetic persistence fixture only.",),
            ),
        )
    )
    decision_inputs = RotationDecisionInputs(
        generation_request=generation_request,
        scoring_request=scoring_request,
    )
    return decision_inputs, generation_result, score_rotation_options(scoring_request)


def make_farm(
    *,
    farm_id: PydanticObjectId | None = None,
    owner_user_id: PydanticObjectId | None = None,
) -> Farm:
    """Construct a persisted-looking farm without connecting to MongoDB."""

    return Farm.model_construct(
        id=farm_id or PydanticObjectId(),
        owner_user_id=owner_user_id or PydanticObjectId(),
        name="Private test farm",
        location_key="ejura",
        soil_texture="unknown",
        irrigation_access=None,
        previous_crops=None,
        current_practice=None,
        farmer_priorities=default_farmer_priorities(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


class FakeResultDocument:
    """Capture insert calls as if a Beanie document had been written."""

    saved: list[FakeResultDocument]

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)
        self.inserted = False

    async def insert(self) -> FakeResultDocument:
        self.inserted = True
        self.saved.append(self)
        return self


FakeResultDocument.saved = []


@pytest.fixture(autouse=True)
def reset_fake_document_store() -> None:
    """Keep each test's fake collection isolated from test ordering."""

    FakeResultDocument.saved = []


def run_immediately(awaitable: Any) -> Any:
    """Run a repository coroutine that only awaits immediate in-memory fakes."""

    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("The in-memory repository fake unexpectedly suspended.")


def test_result_document_captures_engine_outputs_and_hides_coordinates() -> None:
    farm = make_farm()
    decision_inputs, generation, scoring = make_decision_artifacts()
    result = RotationResult.model_construct(
        owner_user_id=farm.owner_user_id,
        farm_id=farm.id,
        farm_inputs=FarmDecisionInputSnapshot.from_farm(farm),
        decision_inputs=decision_inputs,
        candidate_generation=generation,
        scoring_result=scoring,
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )

    serialized = result.model_dump(mode="json")

    assert result.schema_version == "ny20-result-v1"
    assert result.candidate_generation.generator_version == generation.generator_version
    assert result.scoring_result.scoring_version == scoring.scoring_version
    assert serialized["farm_inputs"]["location_key"] == "ejura"
    assert "latitude" not in str(serialized).lower()
    assert "longitude" not in str(serialized).lower()
    assert "password" not in str(serialized).lower()
    assert "token" not in str(serialized).lower()


def test_result_model_rejects_duplicate_environmental_snapshot_references() -> None:
    snapshot_id = PydanticObjectId()
    inputs, _, _ = make_decision_artifacts()

    with pytest.raises(ValidationError, match="references must be unique"):
        RotationDecisionInputs(
            generation_request=inputs.generation_request,
            scoring_request=inputs.scoring_request,
            environmental_snapshot_ids=(snapshot_id, snapshot_id),
        )


def test_repository_derives_farm_reference_and_inserts_one_immutable_record() -> None:
    FakeResultDocument.saved = []
    owner_user_id = PydanticObjectId()
    farm = make_farm(owner_user_id=owner_user_id)
    decision_inputs, generation, scoring = make_decision_artifacts()
    repository = RotationResultRepository(FakeResultDocument)

    result = run_immediately(
        repository.create_for_farm(
            owner_user_id=owner_user_id,
            farm=farm,
            decision_inputs=decision_inputs,
            candidate_generation=generation,
            scoring_result=scoring,
        )
    )

    assert result.inserted is True
    assert result.owner_user_id == owner_user_id
    assert result.farm_id == farm.id
    assert result.farm_inputs.location_key == farm.location_key
    assert result.farm_inputs.farm_updated_at == farm.updated_at
    assert result.candidate_generation == generation
    assert result.scoring_result == scoring
    assert FakeResultDocument.saved == [result]


def test_repository_rejects_a_farm_owned_by_another_authenticated_user() -> None:
    FakeResultDocument.saved = []
    decision_inputs, generation, scoring = make_decision_artifacts()
    repository = RotationResultRepository(FakeResultDocument)
    owner_user_id = PydanticObjectId()
    farm_owner_user_id = PydanticObjectId()

    with pytest.raises(FarmNotOwnedForResult):
        run_immediately(
            repository.create_for_farm(
                owner_user_id=owner_user_id,
                farm=make_farm(owner_user_id=farm_owner_user_id),
                decision_inputs=decision_inputs,
                candidate_generation=generation,
                scoring_result=scoring,
            )
        )

    assert FakeResultDocument.saved == []


def test_repository_rejects_an_unsaved_farm() -> None:
    decision_inputs, generation, scoring = make_decision_artifacts()
    farm = make_farm()
    farm.id = None
    repository = RotationResultRepository(FakeResultDocument)

    with pytest.raises(FarmNotPersistedForResult):
        run_immediately(
            repository.create_for_farm(
                owner_user_id=farm.owner_user_id,
                farm=farm,
                decision_inputs=decision_inputs,
                candidate_generation=generation,
                scoring_result=scoring,
            )
        )

    assert FakeResultDocument.saved == []


def test_result_history_index_is_owner_farm_and_newest_first() -> None:
    index = next(
        index
        for index in RotationResult.Settings.indexes
        if index.document["name"] == ROTATION_RESULT_HISTORY_INDEX_NAME
    )

    assert RotationResult.Settings.name == ROTATION_RESULTS_COLLECTION_NAME
    assert list(index.document["key"].items()) == [
        ("owner_user_id", 1),
        ("farm_id", 1),
        ("created_at", DESCENDING),
    ]


def test_central_registry_discovers_the_feature_document() -> None:
    assert RotationResult in load_document_models()


class FakeFindMany:
    """Record a Beanie-style sort and return configured documents immediately."""

    def __init__(self, documents: list[object]) -> None:
        self.documents = documents
        self.sort_fields: list[tuple[str, int]] | None = None

    def sort(self, fields: list[tuple[str, int]]) -> FakeFindMany:
        self.sort_fields = fields
        return self

    async def to_list(self) -> list[object]:
        return self.documents


def test_history_query_filters_by_owner_and_farm_and_sorts_newest_first() -> None:
    owner_user_id = PydanticObjectId()
    farm_id = PydanticObjectId()
    expected = [object(), object()]

    class FakeReadModel:
        query: dict[str, PydanticObjectId] | None = None
        find_many: FakeFindMany

        @classmethod
        def find(cls, query: dict[str, PydanticObjectId]) -> FakeFindMany:
            cls.query = query
            cls.find_many = FakeFindMany(expected)
            return cls.find_many

    repository = RotationResultRepository(FakeReadModel)
    results = run_immediately(
        repository.list_by_owner_and_farm(
            owner_user_id=owner_user_id,
            farm_id=farm_id,
        )
    )

    assert results == expected
    assert FakeReadModel.query == {
        "owner_user_id": owner_user_id,
        "farm_id": farm_id,
    }
    assert FakeReadModel.find_many.sort_fields == [("created_at", DESCENDING)]


def test_detail_query_filters_by_result_owner_and_farm_ids() -> None:
    result_id = PydanticObjectId()
    owner_user_id = PydanticObjectId()
    farm_id = PydanticObjectId()

    class FakeReadModel:
        query: dict[str, PydanticObjectId] | None = None

        @classmethod
        async def find_one(
            cls,
            query: dict[str, PydanticObjectId],
        ) -> None:
            cls.query = query
            return None

    repository = RotationResultRepository(FakeReadModel)
    result = run_immediately(
        repository.get_by_owner_farm_and_id(
            owner_user_id=owner_user_id,
            farm_id=farm_id,
            result_id=result_id,
        )
    )

    assert result is None
    assert FakeReadModel.query == {
        "_id": result_id,
        "owner_user_id": owner_user_id,
        "farm_id": farm_id,
    }


def test_rotation_result_persistence_round_trip_and_index_in_mongodb() -> None:
    """Optional real-Mongo check; set NOVAYIELD_TEST_MONGODB_URI to enable it."""

    import asyncio
    import os
    from uuid import uuid4

    from pydantic import SecretStr

    from app.core.config import Settings
    from app.database.connection import MongoConnection

    uri = os.getenv("NOVAYIELD_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set NOVAYIELD_TEST_MONGODB_URI to run the MongoDB result test")

    async def run() -> None:
        database_name = f"ny20_result_test_{uuid4().hex}"
        connection = MongoConnection(
            Settings(
                _env_file=None,
                mongodb_uri=SecretStr(uri),
                mongodb_database_name=database_name,
            ),
            document_model_loader=lambda: (RotationResult,),
        )
        connected = False

        try:
            connected = await connection.connect()
            assert connected

            owner_user_id = PydanticObjectId()
            farm = make_farm(owner_user_id=owner_user_id)
            decision_inputs, generation, scoring = make_decision_artifacts()
            repository = RotationResultRepository()
            created = await repository.create_for_farm(
                owner_user_id=owner_user_id,
                farm=farm,
                decision_inputs=decision_inputs,
                candidate_generation=generation,
                scoring_result=scoring,
            )
            reloaded = await RotationResult.get(created.id)

            assert reloaded is not None
            assert reloaded.owner_user_id == owner_user_id
            assert reloaded.farm_id == farm.id
            assert reloaded.farm_inputs.location_key == "ejura"
            assert reloaded.candidate_generation == generation
            assert reloaded.scoring_result == scoring

            indexes = await RotationResult.get_pymongo_collection().index_information()
            assert ROTATION_RESULT_HISTORY_INDEX_NAME in indexes
            assert indexes[ROTATION_RESULT_HISTORY_INDEX_NAME]["key"] == [
                ("owner_user_id", 1),
                ("farm_id", 1),
                ("created_at", -1),
            ]
        finally:
            try:
                if connected:
                    await connection.client.drop_database(database_name)
            finally:
                await connection.close()

    asyncio.run(run())
