# NY-8 Rotation Candidate Generation

## Boundary

`app.decisions.rotation` defines the pure contracts and candidate generator for NY-8. It makes no NASA requests, database calls, API responses, or filesystem writes. It does not calculate criterion ratings or rank candidates; those belong to the second NY-8 implementation subtask.

## Inputs and output

- A request contains exactly three chronologically ordered event windows belonging to one plot, evidence status for whether those events are consecutive, a candidate crop library, optional sourced prior crop history, and an optional sourced three-event current-practice sequence.
- The default candidate library is the six MVP candidates approved in the NY-14 research decision. Their inclusion records area-level crop presence only; suitability traits remain unknown.
- The generator enumerates the Cartesian product of the candidate crop IDs across the three event slots in stable crop-ID order. Six candidates produce 216 mechanical combinations.
- A known current-practice sequence is emitted first as a `baseline`. Its identical generated alternative is omitted, so the baseline replaces one combination and the output remains 216. An absent current-practice record produces no baseline.
- Every output includes its event/crop mapping, generator version, review readiness, and rule findings. A baseline retains its source reference. IDs are deterministic for the same sequence and kind.

## Safety rules

- ROT-001 validates the event structure and requires locally validated evidence that the three events are consecutive on one plot. Invalid shape/plot/date input is rejected while constructing the request; unverified continuity is marked `needs_review`.
- ROT-002 marks missing prior crop history `needs_review`; it never infers fallow or an unreported crop.
- ROT-003 marks unknown or provisional calendars `needs_review` and does not apply calendar-dependent hard exclusions.
- NY14-SUITABILITY marks crop-specific suitability as `needs_review` unless that evidence is locally validated.
- ROT-004 marks repeated crops for review but does not ban them. NY-15 does not support a blanket repeated-crop exclusion.
- No crop-family, nitrogen-credit, water, soil, disease-break, or yield rule is inferred or applied here.
- Provisional and locally validated crop, calendar, or continuity claims require a source reference. Unknown status can remain unsourced, but it results in review where the information is needed.
- Source references should be citation or record IDs; do not put farm coordinates, credentials, or other private values in them.

## Relationship to the public profile

`analysis_docs/research/ny-8-public-demo-profile.md` is an area archetype, not a farm record. Its historical month windows are not approved planting calendars, prior plot history is unknown, and no NASA response values are included. Therefore it cannot currently produce rank-ready recommendations. Unit tests use explicitly synthetic fixtures to verify mechanics; those fixtures are not demo data or agronomic evidence.

## Assessment and ranking

The generator is followed by the versioned crop library and pure sequence
assessment in `app.decisions.crop_profiles` and `app.decisions.crop_evidence`.
The assessor records event-level calendar/suitability review state and
source-scoped predecessor/successor evidence; it does not add scores for
unsupported relationships. NY-9 requires at least two usable NASA indicators
for each past analysis period before it can assess the primary water criterion.
See [NY-8 assessment and scoring](rotation-scoring.md) for the provisional
four-criterion weighted ranking policy and response summary. Missing evidence
in the preferred four-criterion mode selects the documented fallback; the
generator itself does not score or rank candidates.

## Local checks

From `backend/`, run `python -m pytest tests/test_rotation_generation.py` and `python -m ruff check app/decisions tests/test_rotation_generation.py`.
