# NY-8 Rotation Assessment and Top-Three Selection

## Product policy

New results use `ny8-scoring-v3` and all four PRD criteria:

- Water resilience
- Soil-health potential
- Yield-stability proxy
- Labour feasibility

When no farmer priorities are saved, each criterion receives 25%. Otherwise, the four saved priority point values are normalized to percentages. Those weights can change the ranking, but cannot override a candidate that fails a documented hard constraint. The API returns both the equal-weight and selected-priority comparison views, indicates whether priorities change the displayed order, and explains criterion gains and concessions between adjacent options.

A rank is produced only if every alternative in the comparison has assessed evidence for all four criteria using a comparable basis. Missing or incomparable evidence is not scored as zero, neutral, or redistributed across other weights: the overall rank is withheld and the available assessments remain visible. The ranking is provisional, not an agronomic validation. The response contains no more than three alternatives and keeps a known baseline separate.

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

The current assessor emits soil health, yield stability, and labour feasibility as `not_assessed` because it lacks comparable sequence evidence and/or required farm inputs. This means the current real workflow correctly withholds the overall ranking, even if some water evidence is available. It must not fall back to a water-only order.

## Ranking method

1. Exclude candidates only when an explicit hard constraint has outcome `failed`. User preferences cannot reinstate those candidates.
2. Confirm that all four criteria are assessed for every remaining alternative and share a comparison basis criterion by criterion. If any assessment is missing or incomparable, withhold the overall rank without reweighting.
3. Map qualitative ratings to ordinal values: High=3, Moderate=2, Low=1. Multiply each by its normalized priority share and compare the weighted sums. Fractions are used internally for deterministic exact ordering.
4. Return the top three alternatives, preserving equal weighted totals as ties. Candidate ID supplies stable display order within a tie, not agronomic preference.
5. Return criterion ratings, source references, confidence, assumptions, rating basis, selected and equal weights, sensitivity, and trade-off explanations. The baseline remains separate.

The weighted ordinal sum is an implementation choice. It assumes equal spacing between High, Moderate, and Low and is compensatory: a gain on a high-priority criterion can offset a weaker rating on another criterion. Therefore, every result must show the criterion strengths and concessions and must not imply that four criteria automatically make the decision more reliable. Reliability still depends on comparable evidence.

## API response and audit summary

The owner-scoped `RotationResultResponse` contains the separate baseline, selected options, equal-weight and farmer-priority views, ranking status/reasons, per-criterion evidence, pairwise trade-offs, NASA snapshot IDs and indicator provenance, plus generator, crop-library, assessment, rule-set, and scoring versions. It does not return the persisted 216-item candidate-generation list.

`candidate_pool_summary` reports generated, excluded, review-needed, fully assessed, rankable, and returned counts. `total_assessed` counts only candidates with all four criteria assessed. `total_rankable` excludes the separate baseline. A generated-pool count of 216 is not 216 recommendations; the public response contains at most three alternatives.

## Synthetic test example

Synthetic complete ratings should be used to verify the scoring mechanics, not presented as NovaYield evidence. For example, one option might rate High in water and Low in the other three criteria, while another has the reverse pattern. Equal weights can tie them; a farmer's water-heavy weights can move the first ahead. The response should identify both the gain (water) and concessions (soil, yield stability, and labour). Actual results remain withheld unless research and required farm inputs support comparable ratings across all four criteria.

## Checks

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_crop_profiles_and_assessment.py tests\test_rotation_scoring.py tests\test_environmental_workflow_api.py tests\test_rotation_result_api.py -q
.\.venv\Scripts\python.exe -m ruff check app tests
```
