# NY-20 Rotation Result Persistence

## Boundary

`app.models.rotation_results` owns the Beanie document and its collection index. `app.repositories.rotation_results` inserts and retrieves already-generated NY-8 results. The feature does not score, call NASA, or orchestrate generation; NY-9 calls the save method and composes the feature router into the versioned API.

## Stored record

Each `rotation_results` document stores:

- `owner_user_id` and `farm_id` as MongoDB ObjectId references. They are application-level references, not relational foreign keys.
- `created_at` in UTC and `schema_version` for the stored record shape.
- `farm_inputs`, a snapshot of the location key, soil texture, irrigation access, previous crops, current-practice note, farmer priorities, and the farm's update timestamp at generation time. It deliberately contains no coordinates, farm name, user email, or credentials.
- `decision_inputs`, the NY-8 candidate-generation request and scoring evidence/priority request. The environmental indicator DTOs in that evidence retain their source, period, units, coverage, retrieval time, spatial resolution, and live/cached/unavailable state. `environmental_snapshot_ids` point back to the persisted NY-6 snapshots when available.
- `candidate_generation` and `scoring_result`, the outputs as NY-8 produced them. The nested `generator_version` and `scoring_version` are the rule/engine version identifiers currently defined by NY-8; no separate crop-rule bundle version is invented by NY-20.

The original inputs and output are both retained so later farm edits or code changes do not rewrite the explanation for an earlier result. Missing evidence and unavailable indicators remain represented by NY-8's explicit status fields; the persistence layer does not fill missing values or recalculate scores.

## Index

Beanie declares `ix_rotation_results_owner_farm_created_at` on:

```text
owner_user_id ASC, farm_id ASC, created_at DESC
```

This supports newest-first history for one authenticated owner's farm. A detail query will also constrain by owner and farm and then use MongoDB's built-in `_id` index for the result ID. The index is non-unique because one farm can have many historical recommendations. No TTL index is used; NY-20 does not define a history expiry policy.

## Write contract

`RotationResultRepository.create_for_farm` accepts the authenticated owner's ID and a farm document that NY-9 has already authorized. It verifies the farm's stored owner matches that caller, derives `farm_id` and the profile snapshot from the farm document, then inserts one result. It does not accept owner or farm IDs from a request body and exposes no update/delete operation.

The feature model uses NY-4's `@register_document_model` hook. Its module is auto-discovered by the central Beanie registry; this feature must not edit the shared registry, Mongo connection, app entry point, or router registry.

## Read routes

The feature router factory exposes two authenticated read routes for NY-9 to mount:

```text
GET /api/v1/farms/{farm_id}/rotation-results
GET /api/v1/farms/{farm_id}/rotation-results/{result_id}
```

Both routes first confirm the farm belongs to the authenticated user. The repository then filters by `owner_user_id` and `farm_id`; detail retrieval also filters by the result `_id`. Missing and non-owned farms return the same 404, as do missing or non-owned results. The response DTO includes the farm input snapshot, candidate-generator version, scored decision options, criterion explanations, and indicator provenance. It returns the scored options rather than the entire generated candidate set, which may be much larger than the options being presented. It does not serialize the internal owner ID, raw snapshot ObjectIds, credentials, or session tokens.
