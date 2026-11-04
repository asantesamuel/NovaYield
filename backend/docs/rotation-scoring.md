# NY-8 Rotation Assessment and Top-Three Selection

## Product policy

New `ny8-scoring-v2` results follow Product Owner Decision 11:

- Water resilience is the fixed primary criterion.
- Soil-health potential can break a water tie only when every option in that tie
  has comparable, evidence-backed soil evidence.
- Yield stability and labour are not scored in this version.
- Farmer priority points and weighted profiles are retained only to read legacy
  records; they do not change new results.
- Return at most three alternatives. Return a known current-practice baseline
  separately.

The original PRD and the earlier research handoff described four criteria and
farmer-adjustable weights. Decision 11 narrowed the approved implementation.
Restoring four weighted criteria or changing baseline-plus-three to
baseline-plus-two requires an explicit Product Owner scope change.

## Request-to-result path

The existing authenticated NY-9 route is the orchestration boundary:

1. Load the farm with the authenticated owner filter and resolve its supported
   location.
2. Retrieve cached/persisted NASA POWER snapshots for the farmer-reported past
   season periods; calculate the three NY-13 indicators.
3. Build three future planting-event slots separately from those historical
   NASA periods.
4. Generate the six-crop Cartesian product and include a known baseline once.
5. Assess every generated candidate through the pure crop-evidence module.
6. Pass the evidence DTOs to the existing `score_rotation_options()` function.
7. Persist the generated pool and selected result through NY-20, then map it to
   `RotationResultResponse`.

The scorer does not call NASA or MongoDB. Profile loading and assessment are
pure functions in `app.decisions.crop_profiles` and
`app.decisions.crop_evidence`. Route wiring stays in `app.api.workflows`.

## Evidence and criterion behavior

The crop library is versioned as `ny8-crop-library-v1`. A profile can hold
identity, variety, production system, calendar, maturity, and individually
provenanced traits. Only supported facts are populated. The five desk-researched
water classes remain provisional; rice stays unassessed until the production
system is known. See [Crop Library and Sequence Assessment](crop-library-and-assessment.md)
and the [crop-by-criterion evidence matrix](../../analysis_docs/research/ny-8-crop-criterion-evidence-matrix.md).

For each of the three past farmer-reported NASA periods, at least two of the
three approved indicators must have usable values. A usable indicator has a
value and is not marked unavailable. Partial results remain partial with their
coverage metadata; no new minimum coverage percentage is invented. If a period
has fewer than two usable indicators, water is `not_assessed` and the ranking
is withheld. The existing NY-13 policy permits two reliable indicators when
one of three is unavailable.

When environmental context is available, a sequence uses its least
water-resilient crop as the conservative sequence rating. A candidate with an
unassessed crop, currently rice without its ecology, cannot enter the primary
ranking. NASA history is retained in the output but does not adjust crop
classes: these past values are not future weather, crop-stage data, a soil
moisture measurement, or a crop-water balance.

Soil is emitted as `not_assessed` until comparable sequence-specific evidence
and required management context are available. The assessor records ordered
transitions from the last reported crop to the first candidate crop, then
between each candidate event. Cited cowpea/maize and groundnut/maize research
remains `needs_review` without variety, residue, fertility, and local-transfer
context. No legume or family-based bonus is awarded.

## Ranking and ties

1. Exclude candidates only when an explicit hard constraint has outcome
   `failed`. Unknown calendars, unvalidated suitability, and crop repetition
   are review warnings, not automatic exclusions.
2. Compare candidates with assessed water evidence on one shared basis, High
   before Moderate before Low. Incompatible water bases withhold the ranking.
3. Leave options with missing primary evidence unranked. If no alternatives
   have comparable primary evidence, return ranking status `withheld`.
4. Within a water tie, use soil only if every member has an assessed soil rating
   on the same basis. Otherwise preserve the tie.
5. Return at most three alternatives. Candidate ID provides stable display
   order inside a tie; it is not an agronomic preference. If the three-item cap
   cuts through a tied group, `tie_at_limit` and the rationale state that equal
   options were omitted.

The ranking is deterministic and provisional. Qualitative classes are not
probabilities or numeric measurements. A rank never claims guaranteed yield,
measured soil improvement, crop water sufficiency, profitability, or locally
validated planting advice.

## API response and audit summary

The owner-scoped `RotationResultResponse` contains the separate baseline,
selected `scoring_result.options`, tie/withholding details, criterion evidence,
ordered transition assessments, NASA snapshot IDs and indicator provenance,
plus generator, crop-library, assessment, rule-set, and scoring versions. It
does not include the persisted 216-item candidate-generation list.

`candidate_pool_summary` reports:

- `total_generated`: generated alternatives plus baseline, if any.
- `total_excluded`: candidates removed by failed hard constraints.
- `total_needing_review`: generated candidates whose structural readiness is
  `needs_review` (this includes nonblocking calendar/suitability warnings).
- `total_assessed`: candidates with an assessed primary water criterion,
  including the separate baseline when assessed.
- `total_rankable`: comparable ranked alternatives, excluding the baseline.
- `total_returned`: selected alternatives plus the separate baseline, if any.

The `candidate_count` field remains an audit count. Seeing `216` there does not
mean 216 recommendations are returned. The public response has no more than
three alternatives; the complete pool remains in the private NY-20 result for
traceability.

## Synthetic test example

This is a fabricated test-only example, not a NovaYield crop assessment:

| Candidate | Synthetic water class | Soil | Rank group |
| --- | --- | --- | --- |
| `test-a` | High | Not assessed | 1 |
| `test-b` | Moderate | Not assessed | 2 |
| `test-c` | Low | Not assessed | 3 |

It demonstrates only the ordering rule. If `test-a` and `test-b` were both
High, they would share a rank group. Soil would not decide between them because
it is unassessed.

## Checks

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_crop_profiles_and_assessment.py tests\test_rotation_scoring.py tests\test_environmental_workflow_api.py tests\test_rotation_result_api.py -q
.\.venv\Scripts\python.exe -m ruff check app tests
```
