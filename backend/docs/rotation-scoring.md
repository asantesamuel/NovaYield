# NY-8 Qualitative Comparison and Ranking

## Boundary

`app.decisions.scoring` aggregates evidence-backed qualitative assessments for the four PRD criteria. It performs no NASA, MongoDB, API, or filesystem I/O and does not infer crop ratings from crop names. Agronomic assessment rules and locally validated crop traits remain separate inputs; the module owns weight normalization, validity gating, comparison, sensitivity, tie handling, and rank withholding.

## Inputs

- Each candidate has exactly one `CriterionEvidence` record for water resilience, soil-health potential, yield-stability proxy, and labor feasibility.
- A scored option retains its three-event crop sequence and the source candidate's rule findings. NASA-derived `EnvironmentalIndicator` DTOs can be attached to criterion evidence and are returned with their source, period, units, coverage, resolution, retrieval time, and live/cached/unavailable status intact.
- An assessed rating must include a rationale, source reference, confidence, and a `comparison_basis`. Options can be compared on a criterion only when every option has assessed evidence using the same basis.
- Missing data is represented as `not_assessed` with a `None` rating. The model rejects a hidden number or confidence attached to a not-assessed criterion. Attached NASA indicators with partial or unavailable coverage also prevent an overall rank; complete cached indicators retain their cached provenance and can be compared.
- Each option can include hard-constraint outcomes. A failed hard constraint excludes that option before weighting; a hard constraint that needs review preserves partial criterion output but withholds the overall rank. Farmer priorities do not affect these outcomes.
- NY-8 generation findings for continuity, prior history, calendar validation, and crop suitability also block a definitive rank while they remain `needs_review`. ROT-004 repeated-crop review remains a visible warning, not a hard exclusion.

## Weighting and ordering

- The default profile is 25 importance points per criterion.
- Farmer priorities accept 0–100 importance points per criterion and normalize the four values to visible percentages totaling 100. Percentages are rounded to four decimal places with the final non-zero criterion absorbing the rounding remainder. A zero total is invalid. Zero weight for a criterion does not bypass the requirement for comparable evidence across all four criteria.
- Internally, High/Moderate/Low map to ordinal ordering points 3/2/1 for weighted ordering. These points and composite totals are not returned or presented as measurements; the UI receives qualitative categories, disclosed weights, and tie-aware rank groups. The equal spacing is an implementation choice and should be revisited if the team adopts a different ordinal aggregation method.
- Equal-weight and selected-weight rank groups are both returned. A changed ordering is marked `weight_sensitive`; equal groups are kept tied and sorted by candidate ID only for stable display.
- If fewer than two options remain, evidence is missing/incomparable, or a blocking rule needs review, rank groups are withheld with reasons. Per-criterion ratings and their unchanged weights remain available; no missing value is changed to zero or replaced by redistributed weight.
- The scorer orders the candidate set it receives. It does not choose two alternatives from the 216 mechanical combinations produced by the generator; the public Ejura profile lacks evidence for a defensible candidate-selection policy or ranking.

## Current evidence limitation

The Ejura public profile has no plot-level history, locally validated crop suitability/calendar, NASA response values, or comparable evidence for all four criteria. It must therefore produce review/withheld behavior rather than a ranked recommendation. Scoring tests use synthetic values solely to verify aggregation, constraints, missingness, sensitivity, and ties; they are not demo or agronomic evidence.

## Local checks

From `backend/`, run `python -m pytest tests/test_rotation_scoring.py` and `python -m ruff check app/decisions/scoring.py tests/test_rotation_scoring.py`.
