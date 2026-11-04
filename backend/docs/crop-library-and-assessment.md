# NY-8 Crop Library and Sequence Assessment

## Active project contract

The code follows Product Owner Decision 11: water resilience is the fixed
primary criterion; soil-health potential can refine a water tie only when its
evidence is comparable. Yield stability and labour are not scored in NY-8 v2,
and farmer priority weights do not change the order. The pasted implementation
brief's four weighted criteria and baseline-plus-two response would reverse
those approved choices, so this implementation preserves Decision 11.

## Versioned crop profiles

`app.decisions.crop_profiles` owns `CROP_LIBRARY_VERSION` and the six approved
crop records. `CropProfile` has optional identity, variety, production-system,
maturity, calendar, and trait fields. `CropTraitEvidence` records a trait value
or range, unit, evidence status, source, study location/system, confidence,
applicability, and limitations. Provisional or locally validated traits need a
source reference. A trait marked `unknown` cannot carry an inferred value.

The current library deliberately populates only source-backed water evidence:

| Crop | Current trait state | Key limit |
| --- | --- | --- |
| Maize | Provisional water resilience `low`; FAO seasonal range 500–800 mm | Generic crop range; not local irrigation advice |
| Cowpea | Provisional `moderate`, low confidence | Ghana studies vary by genotype, environment, and irrigation context |
| Groundnut | Provisional water resilience `high`; FAO seasonal range 500–700 mm | Generic crop range; resilience is not low water demand |
| Cassava | Provisional `moderate` | Tolerant after establishment but sensitive in its first three months |
| Yam | Provisional `low`, low confidence | Broad West African moisture/duration evidence |
| Rice | Water resilience not assessed | Upland, lowland, and irrigated production systems cannot share one rating |

Scientific names, local names, varieties, detailed calendars, soil traits,
stage-specific responses, and most other characteristics remain unknown until
the research handoff supplies evidence. This is intentional. Do not add an
empty or guessed value merely to make a profile look complete.

The current profiles are a small reviewed library, not a general crop database.
To add a crop, add its profile, cite each populated trait independently, record
the production system and study limits, add it to the approved candidate set,
then update tests and the crop-library version.

## Sequence and transition assessment

`app.decisions.crop_evidence.build_crop_evidence_option()` is pure: it receives
a generated candidate, past environmental indicators, farm context, and prior
crop history. It does no HTTP, MongoDB, or filesystem work.

For the primary water criterion, it checks all three event crops against the
same library. If any crop lacks a comparable class, including rice without its
production system, the sequence water criterion is `not_assessed`. Otherwise,
the weakest crop's provisional resilience class becomes the sequence class.
That conservative bottleneck prevents an average from hiding a vulnerable
season. It is an implementation rule, not a locally validated threshold.

Before assessment, NY-9 checks the three farmer-reported past periods. Each
period needs at least two usable values among the approved NASA indicators
(`PRECTOTCORR`, `T2M`, `T2M_MAX`). An indicator counts only when it has a value
and is not unavailable. Partial values remain partial and carry coverage
metadata; the code adds no coverage percentage threshold. If a period has fewer
than two usable indicators, the primary criterion is not assessed and the rank
is withheld under the existing NY-13 indicator policy.

Past NASA indicators are attached for provenance and historical context. They
do not change the crop-level resilience class and are not used as a future
forecast, field-rainfall measurement, or water balance. Future recommendation
slots remain separate from past NASA analysis periods.

The assessor evaluates three ordered transitions: the last reported crop to
the first candidate event, then event 1 to 2 and event 2 to 3. The library
contains narrowly scoped cowpea-to-maize and groundnut-to-maize study records.
Because variety, residue management, soil fertility, and Ejura transfer are not
known, those transitions return `needs_review`. Other pairs return
`not_assessed`. Neither state creates an automatic nitrogen credit or soil
rating. Crop family alone never establishes an agronomic benefit.

Soil-health potential is currently `not_assessed`. The optional tie-break only
becomes active when every option in a water tie has a sourced rating on one
common comparison basis. The current Farm profile does not capture residue
handling or measured soil fertility, and the cited Ghana trials are
site/treatment-specific.

## Hard constraints and review warnings

The scorer excludes a candidate only for an explicit `HardConstraintFinding`
with outcome `failed`. Candidate-generation findings such as unknown calendars,
unvalidated suitability, unknown history, and crop repetition remain visible
review warnings. Repeated crops are not blanket exclusions. A source-backed
transition marked `needs_review` is reported in the option but does not become
a hidden score or exclusion.

This distinction keeps data-integrity failures separate from agronomic
uncertainty. Missing water evidence prevents that option from ranking; missing
soil evidence does not block the primary water comparison. A tied group remains
tied unless comparable soil evidence can resolve it.

## Synthetic test example

The following values are fabricated only to illustrate the scorer contract;
they do not describe NovaYield crops or an agricultural recommendation:

| Synthetic option | Water resilience | Soil potential | Result |
| --- | --- | --- | --- |
| `test-option-a` | High | Not assessed | First rank group |
| `test-option-b` | Moderate | Not assessed | Second rank group |
| `test-option-c` | Low | Not assessed | Third rank group |

The fixed water-first order determines the groups. Soil remains visible as
missing, so it neither adds points nor changes the ordering. Identical water
classes would remain tied; candidate ID only supplies stable display order.

## Versions and verification

Each persisted decision input records the crop-library, assessment, and rule
set versions. The result also records the candidate-generator and scorer
versions, NASA snapshot IDs, and a candidate-pool summary. The full generated
pool remains in the owner-scoped result record for audit; the frontend response
contains no more than three alternatives and a separate baseline.

From `backend/`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_crop_profiles_and_assessment.py tests\test_rotation_scoring.py tests\test_environmental_workflow_api.py tests\test_rotation_result_api.py -q
.\.venv\Scripts\python.exe -m ruff check app tests
```

The public Ejura area archetype is not an individual farm and has no asserted
plot history or actual NASA values. It is not a rank-ready recommendation
profile. Synthetic tests verify the ranking mechanics only.
