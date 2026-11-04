# NY-8 Rotation Assessment and Top-Three Selection

## Product policy

New results use `ny8-scoring-v4` and expose all four PRD criteria:

- Water resilience
- Soil-health potential
- Yield-stability proxy
- Labour feasibility

The scorer selects one ranking mode for each request, after applying hard constraints:

- **Four-criterion mode:** used when all eligible alternatives have assessed, comparable evidence for water resilience, soil-health potential, yield-stability proxy, and labour feasibility.
- **Water/soil fallback:** used when four-criterion comparability is incomplete. Compare alternatives with common water evidence; include soil health only if every water-assessed alternative has comparable soil evidence. If soil is incomplete or incomparable, rank by water alone.

Normalize farmer priority points only over criteria used by the selected mode. When no applicable priority points exist, use equal weights across those criteria. Inactive criteria receive 0% effective weight and their saved points are identified as ignored. A water-only fallback necessarily gives water 100% weight, so preferences for missing soil/yield/labour evidence cannot change that order. If fewer than two alternatives have comparable water evidence, return no ranked shortlist. Never assign missing ratings or use a water value from a different comparison basis. Hard constraints are applied first and cannot be overridden by priorities.

The result identifies `ranking_mode` and `ranking.criteria_used`, returns equal-weight and selected-priority rank groups, reports unranked alternatives, and explains criterion strengths/concessions for displayed pairs. Rankings remain provisional, not validated agronomic advice. Return no more than three alternatives and keep a known baseline separate.

## Request-to-result path

The authenticated NY-9 route is the orchestration boundary:

1. Load the farm with the authenticated owner filter and resolve its supported location.
2. Retrieve cached/persisted NASA POWER snapshots for farmer-reported past periods and calculate the NY-13 indicators.
3. Keep those historical analysis periods separate from future recommendation-season slots.
4. Generate the six-crop Cartesian product and include a known baseline once.
5. Assess every generated candidate through the pure crop-evidence module.
6. Pass the evidence DTOs and the farm's saved priorities to `score_rotation_options()`.
7. Persist the generated pool and selected result through NY-20, then map it to `RotationResultResponse`.

The scorer does not call NASA or MongoDB. Profile loading and assessment are pure functions in `app.decisions.crop_profiles` and `app.decisions.crop_evidence`; route wiring stays in `app.api.workflows`.

## Current evidence status

The crop library is versioned as `ny8-crop-library-v1`. The five desk-researched water classes remain provisional, and rice remains unassessed until its production system is known. Soil-health ratings require comparable sequence evidence and management context. Current sources do not establish comparable yield-stability ratings for the candidate three-event sequences. Published operation-day estimates do not establish labour feasibility for a farm without labour availability, area, timing, and machinery/service inputs. See [Crop Library and Sequence Assessment](crop-library-and-assessment.md) and the [crop-by-criterion evidence matrix](../../analysis_docs/research/ny-8-crop-criterion-evidence-matrix.md).

For each of the three farmer-reported NASA periods, at least two of the three approved indicators must have usable values. NASA history is provenance and historical context; it does not become future weather, a field-rainfall measurement, soil moisture, or a crop-water balance.

The current assessor emits soil health, yield stability, and labour feasibility as `not_assessed` because it lacks comparable sequence evidence and/or required farm inputs. The real workflow therefore uses water-only fallback for alternatives with assessed water evidence; sequences containing unassessed rice remain outside that ranked subset. Farmer priorities on unavailable criteria are disclosed and cannot influence a water-only order. Do not claim that missing criteria were scored.

## Ranking method

1. Exclude candidates only when an explicit hard constraint has outcome `failed`. User preferences cannot reinstate those candidates.
2. Select four-criterion mode only if all four criteria are comparable for every remaining alternative. Otherwise select the documented water/soil fallback for the whole comparison.
3. In fallback mode, leave alternatives without comparable water evidence unranked. Use soil alongside water only when its ratings are comparable across all water-assessed alternatives; otherwise use water alone.
4. Normalize priorities over the criteria selected for the mode. If none of the farmer's positive points apply, use equal weights over those criteria. Disclose weights for unused criteria as 0% and state that their preferences were ignored.
5. Map qualitative ratings to ordinal values: High=3, Moderate=2, Low=1. Multiply by effective priority shares and compare weighted sums. Fractions are used internally for deterministic exact ordering.
6. Return the top three alternatives, preserving equal weighted totals as ties. Candidate ID supplies stable display order within a tie, not agronomic preference.
7. Return criterion ratings, source references, confidence, assumptions, rating basis, selected mode, criteria used, effective selected/equal weights, sensitivity, and trade-off explanations. The baseline remains separate.

The weighted ordinal sum is an implementation choice. It assumes equal spacing between High, Moderate, and Low and is compensatory: a gain on a high-priority criterion can offset a weaker rating on another criterion. Therefore, every result must show the criterion strengths and concessions and must not imply that four criteria automatically make the decision more reliable. Reliability still depends on comparable evidence.

## API response and audit summary

The owner-scoped `RotationResultResponse` contains the separate baseline, selected options, equal-weight and farmer-priority views, ranking status/reasons, per-criterion evidence, pairwise trade-offs, NASA snapshot IDs and indicator provenance, plus generator, crop-library, assessment, rule-set, and scoring versions. It does not return the persisted 216-item candidate-generation list.

`candidate_pool_summary` reports generated, excluded, review-needed, fully four-criterion-assessed, rankable, and returned counts. `total_assessed` counts only candidates with all four criteria assessed; `total_rankable` counts the water-comparable fallback subset or full-mode comparison set and excludes the baseline. A generated-pool count of 216 is not 216 recommendations; the public response contains at most three alternatives.

## Synthetic test example

Synthetic complete ratings should verify four-criterion mechanics, not serve as NovaYield evidence. In fallback tests, two options can have comparable water and soil ratings but incomplete yield evidence; changing farmer weights between water and soil should change their order, and the explanation should name the resulting gain and concession. In the current real workflow, soil is not comparable, so water-only fallback can rank only the water-assessed subset. Synthetic fixtures must never be presented as agronomic evidence.

## Checks

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_crop_profiles_and_assessment.py tests\test_rotation_scoring.py tests\test_environmental_workflow_api.py tests\test_rotation_result_api.py -q
.\.venv\Scripts\python.exe -m ruff check app tests
```
