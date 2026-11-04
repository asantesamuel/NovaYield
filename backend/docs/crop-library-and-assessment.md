# NY-8 Crop Library and Sequence Assessment

## Active project contract

Product Owner Decision 13 prefers all four criteria when comparable evidence is available, and selects a priority-weighted water/soil fallback when it is not. Soil is included in fallback only when comparable across water-assessed options; otherwise water alone is used. Persisted farm priorities can change order over the criteria used by either mode. A hard constraint is applied before scoring and cannot be overridden by a preference. The response explains gains and concessions between ranked options.

Four-criterion mode requires comparable, assessed evidence for every criterion on every eligible option. Missing evidence stays `not_assessed`; the scorer neither invents a rating nor uses the missing criterion's weight. When that evidence gate fails, the scorer applies the documented fallback to the water-assessed subset. Synthetic complete evidence is used only in tests of four-criterion scoring mechanics.

## Versioned crop profiles

`app.decisions.crop_profiles` owns `CROP_LIBRARY_VERSION` and the six approved crop records. `CropProfile` has optional identity, variety, production-system, maturity, calendar, and trait fields. `CropTraitEvidence` records a trait value or range, unit, evidence status, source, study location/system, confidence, applicability, and limitations. Provisional or locally validated traits need a source reference. A trait marked `unknown` cannot carry an inferred value.

The current library deliberately populates only source-backed water evidence:

| Crop | Current trait state | Key limit |
| --- | --- | --- |
| Maize | Provisional water resilience `low`; FAO seasonal range 500–800 mm | Generic crop range; not local irrigation advice |
| Cowpea | Provisional `moderate`, low confidence | Ghana studies vary by genotype, environment, and irrigation context |
| Groundnut | Provisional water resilience `high`; FAO seasonal range 500–700 mm | Generic range; resilience is not low water demand |
| Cassava | Provisional `moderate` | Tolerant after establishment but sensitive in its first three months |
| Yam | Provisional `low`, low confidence | Broad West African moisture/duration evidence |
| Rice | Water resilience not assessed | Upland, lowland, and irrigated systems cannot share one rating |

Scientific names, local names, varieties, detailed calendars, soil traits, stage-specific responses, and most other characteristics remain unknown unless source-backed. Do not add an empty or guessed value merely to make a profile look complete.

## Sequence assessment

`app.decisions.crop_evidence.build_crop_evidence_option()` is pure: it receives a generated candidate, past environmental indicators, farm context, and prior crop history. It does no HTTP, MongoDB, or filesystem work.

Before assessment, NY-9 checks each of the three farmer-reported historical
periods for at least two usable values among `PRECTOTCORR`, `T2M`, and
`T2M_MAX`. A value counts only when present and not marked unavailable. Partial
coverage remains explicit; no unapproved percentage threshold is invented.
These past NASA windows are environmental context and provenance, never the
future planting slots used to generate the candidate sequence.

- **Water resilience:** If each crop has a comparable provisional class, the sequence takes its least-resilient crop as a conservative bottleneck. A sequence containing a crop without a comparable class, such as rice with no production system, is `not_assessed`. NASA history provides traceable context but does not change crop classes or create a future forecast or field water balance.
- **Soil-health potential:** Current sequence ratings are `not_assessed`. Ghana legume/residue studies are specific to treatments and following crops; variety, residue, soil, and fertility context are absent. Crop family alone does not create a soil benefit.
- **Yield-stability proxy:** Current sequence ratings are `not_assessed`. Reviewed studies are crop-, variety-, site-, and environment-specific and do not provide a common scale for these three-event alternatives.
- **Labour feasibility:** Current ratings are `not_assessed`. Published operation estimates are not farm feasibility evidence; the Farm profile does not provide available labour, plot area, operation timing, or machinery/service access.

The assessor also checks each planting event's calendar/suitability review
state and evaluates three ordered transitions: last reported crop to event one,
then event one to two and two to three. The cited cowpea/maize and
groundnut/maize relationships remain `needs_review` without variety, residue,
soil-fertility, and local-transfer context. A relationship warning supplies no
soil score or nitrogen credit.

The assessor retains citations, assumptions, confidence, and missing-context reasons. It does not turn missing ratings into scores. Since current soil evidence is `not_assessed`, the actual fallback uses water alone; farmer priorities attached to unavailable criteria are ignored and disclosed. The evidence and limitations are recorded in the [crop-by-criterion evidence matrix](../../analysis_docs/research/ny-8-crop-criterion-evidence-matrix.md).

## Hard constraints and review warnings

The scorer excludes a candidate only for an explicit `HardConstraintFinding` with outcome `failed`. Unknown calendars, unvalidated suitability, unknown history, and crop repetition remain visible review warnings unless an approved hard rule says otherwise. A preference weight cannot override a failed rule.

This distinction keeps data-integrity failures separate from agronomic uncertainty. Missing or incomparable four-criterion evidence selects fallback; alternatives without comparable water evidence remain unranked. Available criterion findings stay visible in either case.

## Synthetic test example

Tests may supply fabricated complete ratings to verify deterministic weighting. For example, an option rated High for water and Low on the other three criteria can be compared with an option rated High for soil, yield stability, and labour. Equal and selected weights can yield different orders; the result must disclose the gain and concessions. Such fixture values do not describe NovaYield crops or provide agronomic evidence.

## Versions and verification

Each persisted decision input records the crop-library, assessment, and rule-set versions. The result also records the candidate-generator and scorer versions, NASA snapshot IDs, normalized priority profiles, rank status, and candidate-pool summary. The full generated pool remains in the owner-scoped result record; the frontend response contains no more than three alternatives and a separate baseline.

The public Ejura area archetype is not an individual farm, has no asserted plot history or actual NASA values, and lacks comparable evidence for all four criteria. It is not rank-ready.
