# Analysis and Research Documents

This directory is for Nova Yield's agronomic research, evidence, data-source notes, pilot-region and crop-library decisions, decision-rule assumptions, and analysis experiments. Keep findings traceable to their source and label assumptions that need review by an agronomist or other domain expert.

Use this directory for human-authored research records and reproducible analysis materials. Do not put runtime application data here: user accounts, farm records, decision results, NASA response caches, and other persisted service data belong to the backend's MongoDB layer.

Suggested organization as research work begins:

- `research/` for source reviews and findings.
- `decisions/` for pilot, crop, and agronomic decision records.
- `experiments/` for analytical notebooks, scripts, and analysis tests.

Research findings supplied for implementation should be preserved under `research/` and linked from the relevant backend documentation. The NY-13 NASA POWER inputs and indicators specification is stored in [`research/ny-13-nasa-power-input-specification.md`](research/ny-13-nasa-power-input-specification.md). The source-specific freshness and missing/incomparable-evidence policies are now approved in the [Product Owner decision record](../novayield-research-and-product-decisions.md); the exact public reference points, local calendar, and live NASA response metadata still require validation. The [NY-8 public-data demo profile candidate](research/ny-8-public-demo-profile.md) records verified area-level evidence and explicitly unknown farm-specific inputs.
