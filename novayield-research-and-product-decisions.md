# NovaYield Research and Product Decisions

**Purpose:** Consolidate the research comments on Jira NY-12 through NY-16, compare them with the NovaYield MVP PRD, and identify the approvals needed before the related implementation decisions are treated as final.

**Evidence reviewed:** The five Jira issues and their one comment each, in the Jira project named **Nova Yield** (project key `NY`); and *NovaYield MVP PRD*, version 1.0, dated 15 October 2026, marked “Draft for team alignment.” Jira was reviewed on 29 October 2026. The research comments are dated 24 October 2026.

**Interpretation rule:** Statements below are identified as PRD requirements, reported research findings, recommendations, or open decisions. A desk-based recommendation is not presented as local agronomic validation.

## 1. Executive Summary

The research comments provide a coherent starting design for a one-area, transparent crop-rotation decision-support MVP. They do not yet authorize final local crop rules or a definitive ranking policy.

- **Pilot:** NY-12 recommends Ejura-Sekyedumase Municipality in Ashanti Region as a *provisional* pilot, sampling more than one community/location to represent its north–south variation. Kintampo South is the proposed fallback. The PRD requires one Ghanaian zone but leaves the exact area open. The Product Owner must confirm the pilot geography and demonstration location(s).
- **Crop candidates:** NY-14 recommends maize, cowpea, groundnut, cassava, yam, and rice. This is a reasonable locally grounded candidate library, but differs from the PRD's illustrative examples (maize, cowpea, groundnut, cassava, sorghum, soybean). The PRD permits four to six locally evidenced crops; the Product Owner must approve the proposed substitution.
- **Season calendar:** Ejura-Sekyedumase has materially different rainfall patterns across the municipality. The sources describe broad seasons, not implementation-ready planting windows for every crop, community, variety, and production system. Do not hard-code one municipality-wide date or treat a provisional window as an agronomic recommendation.
- **NASA POWER:** NY-13 specifies daily `PRECTOTCORR`, `T2M`, and `T2M_MAX` inputs and three candidate indicators. NASA POWER's daily service defaults to local solar time unless UTC is requested, and reports meteorological variables at their source-product resolutions. Metadata from the actual response at the approved demonstration location still needs verification.
- **Agronomic rules:** NY-15 supports strict input/season integrity checks now. Repeated-crop bans, family bans, nitrogen credits, disease break intervals, and crop-specific water/soil thresholds should remain inactive until evidence for the specific crop, variety, production system, and pilot community is reviewed.
- **Comparison:** The PRD explicitly requires four criteria, hard constraints before ranking, farmer priorities affecting weights, visible assumptions, reproducibility, and no false precision. NY-16 proposes qualitative ratings, equal 25% provisional weights, evidence confidence separate from performance, sensitivity checks, and explicit missing-data behavior. The equal weights and minimum evidence rule are proposals, not validated values.
- **Product Owner decisions:** Confirm the pilot and points, crop shortlist, handling of unvalidated seasons, whether to show two or three indicators, default/farmer weighting controls, minimum evidence needed for an overall rank, sensitivity display, and the freshness policy for recent NASA data. Decide whether an extension officer/agronomist can review the rules before they are described as locally validated.

No Jira issues or comments were modified. Jira currently shows NY-12 through NY-16 as **In Progress**. NY-16's research comment says it should remain To Do pending approvals, so that ticket's status conflicts with its own comment.

## 2. Consolidated Research Findings

### 2.1 NY-12 — Pilot area

**Source issue:** [NY-12 — Recommend a Ghanaian pilot agroecological area](https://devbysam.atlassian.net/browse/NY-12). The issue has one research decision brief, dated 24 October 2026.

**Desk-based recommendation:** Use **Ejura-Sekyedumase Municipality, Ashanti Region**, as the provisional first pilot, with possible representative communities around Ejura, Kasei, and Anyinasu. Treat the municipality as the pilot geography rather than treating one NASA grid point as the whole municipality. The comment assigns moderate confidence to the geography choice, but low-to-moderate confidence to operational crop calendars and plot-level rules.

The brief compares:

| Candidate | Reported strengths | Main limitations | Research assessment |
| --- | --- | --- | --- |
| Ejura-Sekyedumase | Forest–savanna transition, a locally diverse crop mix, smallholder/rain-fed farming evidence, differing rainfall patterns, and a local maize climate-risk case study. | Conditions differ within the municipality; planting dates shift; some MOFA statistics cited in the brief are historical. | Best balance for an initial transition-zone demonstration, subject to validation. |
| Kintampo South / Kintampo | Diverse crops and transition-zone relevance; the cited profile identifies two maize seasons. | Community-specific planting calendars, soil information, and extension evidence need checking. | Fallback if validation access or usable data are materially better. |
| Northern Guinea/Sudan savanna, such as Upper East | Clearer single main rainy season and a relevant cereal/legume drought-risk context. | A different farming system; dry-season irrigation and local calendars require separate treatment. | Better as a later comparison/expansion area than the first transition-zone pilot. |

The municipal authority describes the south as semi-deciduous forest and the north as Guinea savanna, with bimodal rainfall in the south and unimodal rainfall in the north. The MOFA district profile uses a broad bimodal description. These statements describe different spatial scopes and are a reason to validate the selected communities rather than force one calendar on the whole municipality. The local authority's crop list includes maize, yam, beans, rice, plantain, cassava, and groundnuts. MOFA's list also includes cowpea and other crops. Some production estimates in the MOFA profile are old and should be treated as evidence of crop presence, not as current rankings or yields.

**Initial crop/season framing in the comment:** Start research with maize, yam, cassava, cowpea, and groundnut; consider rice and plantain after community-level checks. Broad major/minor-season dates and a published report of shifted planting dates are not field-ready planting prescriptions. The brief specifically says not to hard-code one municipality-wide planting date.

**Data plan:** Query NASA POWER at two or more representative locations; retain parameter names, units, date coverage, retrieval date, source/grid metadata, and missingness. Compare with a GMet station or local rainfall record if an accessible, suitable record exists. Use SoilGrids for exploratory regional screening only, recording depth and uncertainty. Seek current municipal crop calendars, crop/variety information, farmer planting and harvest windows, soil evidence, and extension coverage.

**Validation actions named in the comment:**

1. Municipal Agriculture Directorate: confirm priority crops, season definitions by community, planting/harvest windows, varieties, and extension coverage.
2. Agronomy/soil specialist: confirm soil groups and variability; identify local surveys or field samples. Do not treat SoilGrids as field diagnosis.
3. Data lead: archive POWER queries for at least two representative locations; document resolution, missingness, coverage, and units; compare with available local observations.
4. Farmer/extension team: validate the five-crop starting shortlist, intercrops/rotations, and differences among communities.

### 2.2 NY-13 — NASA POWER data and indicator specification

**Source issue:** [NY-13 — Define NASA POWER data and indicator specifications](https://devbysam.atlassian.net/browse/NY-13). The issue has one specification comment, version 1.0.

**Source and request contract:** The comment specifies NASA POWER Daily Point API at `https://power.larc.nasa.gov/api/temporal/daily/point`, community `AG`, JSON, inclusive start/end dates, explicit `time-standard=UTC`, and first-release parameters `PRECTOTCORR`, `T2M`, and `T2M_MAX`. It requires a validated demonstration/community point rather than an invented farm coordinate. Private farm coordinates should not appear in public logs or provenance. Each returned parameter's long name, units, fill value, source, and resolution should be retained; fail clearly when a required variable is absent.

**Three candidate P0 indicators:**

| Indicator | Formula | Output unit | Interpretation |
| --- | --- | --- | --- |
| Seasonal precipitation total | Sum valid daily `PRECTOTCORR` values within the selected inclusive season window. | `mm/season`, only if response metadata confirms `mm/day`. | Estimated precipitation represented by the POWER grid cell, not a field rain gauge. |
| Mean daily air temperature | Arithmetic mean of valid daily `T2M` values in the period. | `°C`, verified from response metadata. | Mean near-surface air temperature represented by the source grid. |
| Mean daily maximum air temperature | Arithmetic mean of valid daily `T2M_MAX` values. | `°C`, verified from response metadata. | Mean of daily maximum temperatures, not the single hottest observation. |

The API's response metadata is the runtime authority for units, fill values, and source information. `-999` is commonly cited as a fill value but must be confirmed from the response. Missing values are never zero, never imputed for P0, and partial coverage must include expected/valid/missing counts and coverage percentage. With no valid values, the result is unavailable. A minimum coverage threshold has not been chosen; NY-13 says not to invent one or silently redistribute a criterion's weight.

Season dates must come from a locally reviewed crop/community calendar, not arbitrary calendar years. The comment requires the season label, dates, calendar source/version, and crop/community context to travel with the data. Unvalidated windows must be identified as provisional or unavailable; they must not imply a validated planting recommendation.

Spatially, POWER is gridded/reanalysis data. It is not a farm station, plot-level rainfall, or soil moisture measurement. Native resolution varies by parameter/source, so preserve variable-specific metadata and avoid advertising one universal grid size. A municipality reference point supports area-level screening only.

**NY-13's remaining acceptance checks:** approve demonstration point(s) and crop-specific windows; confirm indicators' crop relevance; choose minimum coverage and freshness policies; verify exact response units/fill values/source/native resolution at an approved point; and decide user wording for provisional windows and partial coverage.

### 2.3 NY-14 — Locally grounded crop library

**Source issue:** [NY-14 — Select a locally grounded 4–6 crop MVP library](https://devbysam.atlassian.net/browse/NY-14). The comment proposes six **candidate library records**, not six validated rule profiles:

| Candidate | Local evidence / classification in the comment | What must remain unknown or provisional |
| --- | --- | --- |
| Maize | Strong local relevance; cereal/Poaceae. Local maize failure research describes rain-fed production and a 2020 minor-season failure. | Do not assign a numerical water demand, drought rating, soil threshold, planting date, or labour score without variety/system evidence. Residue practice varies. |
| Cowpea | Locally reported; grain legume/Fabaceae. | Legume classification does not prove a soil/N benefit. Validate variety, biomass, residues, and practices. No local numeric water/soil/calendar/labour values supplied. |
| Groundnut | Locally reported; food/oilseed legume/Fabaceae. | No fixed N credit, residue benefit, variety-specific thresholds, planting window, or labour class without evidence. |
| Cassava | Local crop evidence; root/tuber, listed as Euphorbiaceae in the comment. | Do not call it drought-proof or automatically low-water. Establishment, variety, duration, and harvest timing matter; local planting/labour categories are unconfirmed. |
| Yam | Local crop evidence; Dioscoreaceae tuber. | Mounding/staking may affect labour, but must be confirmed with farmers. No numeric water/soil threshold, variety/calendar, or labour rating is validated here. |
| Rice | Local crop evidence; cereal/Poaceae. | Do not assume one water regime. Identify upland, rain-fed lowland, or irrigated system, as calendar, water, and management differ. |

The comment defers sorghum/guinea corn (local use needs confirmation), soybean (investment potential is not evidence of common current rotation use), plantain (possible later addition), and generic “beans” (ambiguous without identifying the species). It proposes that crop records include stable ID, local/common/scientific name, variety, family/type, local production evidence, season window and version, sourced traits, residue/fixation facts where supported, labour operations where validated, source/date, confidence, validation status, assumptions, and open questions.

Implementation guidance: seed candidates with evidence statuses such as `unknown`, `not_assessed`, `provisional`, and `locally_validated`; don't fill unknown attributes with guessed categories. A rule needing an unknown trait should return `needs_review` or stay inactive. NY-16 should not reward unverified water/soil benefits. The comment explicitly asks the Product Owner to approve the proposed six-crop substitution before seeding.

### 2.4 NY-15 — Conservative rotation rule specification

**Source issue:** [NY-15 — Document evidence-backed crop-rotation constraints and rules](https://devbysam.atlassian.net/browse/NY-15). The comment defines a rotation as three consecutive **planting events on the same plot**, each tied to an approved local calendar and relevant farm history/management. It says not to generate a sequence until the community/crop-system calendar is approved.

| Rule | Treatment proposed in NY-15 | Evidence status / boundary |
| --- | --- | --- |
| ROT-001: events are not three consecutive locally defined seasons on the same plot | Hard validity gate; reject or mark incomplete, do not rank. | High-confidence data-integrity rule; local season boundaries still need validation. |
| ROT-002: required prior plot/crop history is unknown | `needs_review` for the rule. | High-confidence data-integrity rule. Never infer fallow or another crop. |
| ROT-003: planting window is unconfirmed or outside approved window | Mark provisional/`needs_review` until validated; then may be a hard gate. | Need is clear; exact crop/community dates require extension/farmer confirmation. |
| ROT-004: same crop or related crop repeats | Soft warning/review, not a blanket ban. | General diversity rationale is not a universal local prohibition; the MOFA profile even describes repeated maize under fertilizer use. |
| ROT-005: cereal follows legume | At most a conditional preference, never guaranteed soil score or hard rule. | Depends on variety, fixation, biomass, residues, soil, and inputs. |
| ROT-006: legume residues retained, removed, grazed, burned, or incorporated | Capture as context; no default nitrogen credit. | Management changes the possible nutrient/organic matter effect; local practices need checking. |
| ROT-007: diagnosed pest/pathogen and next crop host | Hard exclusion only with named local diagnosis, authoritative host evidence, and supported break interval. | General rotation principle is established; no pilot-specific hard exclusion is approved. |
| ROT-008: crop water regime incompatible with available water | Hard exclusion only after system-specific local thresholds/access are validated; otherwise `needs_review`. | Rice system especially must be captured; no numeric threshold is validated. |
| ROT-009: soil, drainage, pH, fertility, or slope outside a crop requirement | Hard exclusion only when reliable field input and crop-specific source-backed threshold exist. | Do not infer plot properties from municipality or gridded climate/soil proxies. |
| ROT-010: labour/machinery/operation timing infeasible | Preference/feasibility warning unless farmer confirms a non-negotiable constraint. | Labour is farm/household-specific; capture it rather than infer it. |
| ROT-011: farmer preference conflicts with validated hard constraint | Hard constraint wins; explain why. | Explicit PRD rule. |

Safe P0 behavior now: validate three consecutive events, same-plot history, approved candidate-crop membership, and required inputs; represent missing information explicitly; run farmer preferences only after validity checks; explain exclusions. Keep crop-family bans, repeated-maize bans, nitrogen credits, fixed water/heat thresholds, and pest breaks inactive unless a specific, locally relevant evidence record supports them. If every sequence fails, say no validated sequence is available rather than relaxing constraints to force three options.

Each active rule should retain rule ID, scope, type, effect, rationale, inputs, missing-input behavior, source/date, evidence summary, confidence, validation status, reviewer, and version. The comment identifies seven local review questions: crop/variety windows; observed rotations/intercropping/repeated crops; locally important pests and break intervals; Striga/nematode/root/tuber/soil disease evidence; residue practices; rice production system/water access; and labour, machinery, seed, market, and household feasibility.

### 2.5 NY-16 — Transparent comparison framework

**Source issue:** [NY-16 — Define the transparent MVP comparison and scoring framework](https://devbysam.atlassian.net/browse/NY-16). The proposal is a deterministic multi-criteria decision aid, not crop simulation, yield prediction, soil test, or profitability model.

The proposed evaluation sequence is: validate farm/plot/crop/calendar/history; apply approved hard constraints; assess remaining sequences on the four PRD criteria; apply farmer priorities among valid options; show evidence, unknowns, benefits, trade-offs, and ranking reasons. Preferences cannot rescue an invalid sequence.

| PRD criterion | Proposed inputs | Key limitation |
| --- | --- | --- |
| Water resilience | NY-13 seasonal rainfall and, if later validated, variability/distribution; approved calendar; crop traits; farmer water source/irrigation and reported risks. | Gridded rainfall is not plot rainfall or soil moisture; rainfall total alone cannot establish crop water sufficiency. |
| Soil-health potential | Crop family/legume status, approved rules, residue handling, and credible soil tests/field observations if available. | No claim of measured fertility, organic matter, N gain, or improvement from a crop label alone. |
| Yield-stability proxy | Historical seasonal climate and documented crop/season fit/rules. | Relative risk context only; not a yield or crop-failure probability. |
| Labour feasibility | Farmer-reported labour availability, machinery, timing, and validated crop operations. | Do not infer labour intensity or costs from crop names alone. |

The comment proposes High/Moderate/Low/Not assessed qualitative ratings, with confidence recorded separately. Optional ordinal values (`3/2/1`) may order categories, but the UI should show categories, not imply measurable intervals; `Not assessed` is null, not zero. A 25/25/25/25 profile is suggested only as a neutral placeholder, not a research-derived optimum. Farmer-entered 100 importance points could be normalized to weights; a non-negotiable preference should become a hard constraint only after the condition and evidence are confirmed.

Missing ratings must not become zero, a midpoint, or an undisclosed redistributed weight. The comment recommends a partial comparison with missing criteria/weights visible, or `insufficient_evidence`, instead of a definitive rank when evidence is missing or incomparable. It asks Product Owner and agronomist to approve minimum evidence coverage.

Each option should show sequence, validity, criterion rating/weight/confidence/reason, benefit, trade-off, checked constraints/warnings, missing inputs, assumptions, and default/custom priority provenance. A composite score is conditional on disclosed comparable evidence and method. Recalculate under equal and selected weights; flag sensitivity; make tie-breakers deterministic and present a tie if still equal. Persist rule/scoring versions, timestamp, location/calendar context, sequence, hard-constraint results, criterion inputs/ratings/reasons/confidence, weights, source IDs/dates, NASA state/coverage, assumptions, and sensitivity/tie outcome.

## 3. Questions Answered by the PRD

The PRD is version 1.0, dated 15 October 2026, and marked draft for team alignment. It gives clear answers to the following questions; these should not be presented as unresolved decisions.

| Question | PRD answer | Source section |
| --- | --- | --- |
| What is the MVP's scope boundary? | One selected Ghanaian pilot area, one user journey, a limited locally defensible crop set, and an end-to-end demonstration. | §§1, 3, 4 |
| How many crops and seasons? | Approximately 4–6 local crops; a rotation is three consecutive planting seasons, and the local calendar must be documented rather than assuming one season per year. The example crop list is not a final mandate. | §3; FR-04 |
| What environmental source and period? | Historical NASA POWER precipitation and temperature for a selected location/date range. | §4; FR-02 |
| How many indicators? | At least two understandable NASA-derived indicators; precipitation and temperature summaries are examples. Threshold-based dry-spell/heat metrics need documented thresholds. | §4; FR-03; §11 |
| How many options? | Three sequences: a baseline/current-practice option when known plus two alternatives. | §4; FR-05; §§5, 11, 16 |
| Which comparison criteria? | Water resilience, soil-health potential, yield-stability proxy, and labor feasibility. | P0 Comparison table; FR-06; §7 |
| How must scoring behave? | Hard constraints precede ranking; preferences cannot validate an invalid sequence. Use visible component scores or Low/Medium/High; define any numeric values and avoid false precision; farmer priorities influence weights; weights are provisional and visible; exclude profitability without credible local data; explain benefits/trade-offs/rules; same inputs/data reproduce results. | §7 |
| What must be disclosed about NASA data? | Source, date range, retrieval status, resolution when available, grid limitations, missing/delayed data, cached demo labeling/date range, and indicator calculation/threshold rationale. | FR-09/10; §8; §11; Appendix A |
| What is the fallback principle? | Use a clearly labeled cached/sample dataset if live NASA data is unavailable, and never present sample data as live. | §4; Core user journey; FR-10 |
| What claims are prohibited? | Do not present heuristic ratings as measured soil health, guaranteed yield, precise profitability, field-level satellite soil moisture, or an agronomically validated prescription without evidence. | §§2, 4, 7, 8; Appendix A |
| What minimum field inputs matter? | Location/demo field, soil texture, irrigation access, previous crop(s), and at least one farmer priority. | P0 Field profile; FR-01; §§5, 9 |

The PRD does **not** select the exact pilot location, candidate crop set, season windows, exact two or three indicators, provisional weights, evidence-coverage threshold, cache freshness policy, or expert reviewer. Those remain open in §15 and/or the Jira comments.

## 4. Agricultural Research and Recommendations

This section separates source findings from what NovaYield should do with them. The recommendation is to prevent unsupported rules from becoming active code; it is not a claim that a particular rotation has been locally validated.

### 4.1 Pilot and crop-calendar recommendation

**Evidence:** Ejura-Sekyedumase's municipal profile reports forest conditions in the south, savanna in the north, and different rainfall patterns. The 2024 municipal budget lists maize, yam, beans, rice, plantain, cassava, and groundnuts as prominent crops; some other district statistics in the older MOFA profile are historical. A 2022 study of 40 farmers across Ejura, Kasei, and Anyinasu reports a 2020 minor-season maize failure involving delayed/short rains and fall armyworm; it is a valuable local risk case, not a universal crop model.

**Recommendation:** Keep Ejura-Sekyedumase provisional until the Product Owner confirms it and extension/farmer evidence supports the chosen communities. Use at least two representative sampling locations to avoid concealing the north–south gradient. Build calendars as crop-, variety-, community-, and season-specific ranges with source/version. The Ghana Meteorological Agency's current seasonal forecasts are useful for seasonal risk communication, but a forecast is not a permanent planting calendar. The Ministry of Food and Agriculture's maize guide itself says planting time varies with agroecology, season, and maturity group and should use local weather information.

**Limits:** Municipal profiles are broad and sometimes rely on older statistics; the maize failure study covers one event and 40 farmers in three communities. Neither gives validated planting windows for every crop/variety. No precise demo point has been approved in NY-12/13.

### 4.2 Candidate crop library

**Recommendation:** Use the six NY-14 crops as candidate records only if the Product Owner approves the difference from the PRD examples. Validate crop presence, varieties, system, dates, and farmer relevance with the municipal agriculture office and farmers. Keep trait fields unknown until evidenced. For rice, capture upland/rain-fed lowland/irrigated ecology; official Ghana rice strategy material distinguishes these systems. Do not model “rice” as one water requirement.

**Legume/rotation evidence:** Ghana field studies show that legumes can fix nitrogen and may improve a following maize crop in particular varieties and management settings, but the effect depends on variety, biomass, residue handling, soil, and input regime. A study in Wenchi in Ghana's forest/savanna transition zone measured variety-dependent fixation and succeeding-maize responses; a separate KNUST cowpea experiment found no significant residual fertilization effect on succeeding maize in its 2014 trials. A Kpong study found maize response differed by legume and residue treatment. These findings support recording variety and residue management, not awarding a universal “legume = soil benefit” score or fixed nitrogen credit.

### 4.3 Rotation constraints and local agronomy

**Recommendation:** Activate data-integrity checks first: same plot, three consecutive locally defined planting events, valid history, approved crop record, and known required inputs. For agronomic hard constraints, require a specific crop/variety/community/system scope, named pest/pathogen or crop requirement, source, reviewer, validation status, and a clear missing-data behavior.

**Evidence boundary:** The Ejura 2020 study identifies rainfall failure and fall armyworm as contributors to maize loss. A recent field study of maize/legume intercropping in northern Ghana is adjacent evidence for pest management, but intercropping is not a three-season rotation and northern Guinea savanna is not the Ejura pilot. Neither study establishes a local fall-armyworm break interval for NovaYield. Do not encode a generic “no same family twice,” “no repeated maize,” disease break, or pest-host exclusion without crop- and organism-specific support.

### 4.4 Water, soil, and labor criteria

- **Water:** Seasonal rainfall is environmental context, not field water availability. A water rating must also depend on approved season dates, irrigation/water access reported for the farm, and sourced crop/system traits. Do not claim water sufficiency, soil moisture, or drought diagnosis from seasonal precipitation alone.
- **Soil:** SoilGrids can support broad screening with property, depth, map version, and uncertainty, but it is a modeled 250 m prediction, not a field sample. Prefer farmer/extension information or a soil test for field-level suitability rules. Never use NASA climate values as soil measurements.
- **Labor:** Ask about labour availability, hired/household labour, machinery, and operation timing. Local field practices vary; for example, the Ejura maize failure study describes mechanized ploughing/harvest and manual sowing/weed clearance among surveyed farmers. That observation is not a universal labour category for other crops/farms. Yam mounding/staking should be asked about rather than automatically scored.

### 4.5 Rating evidence and validation

Use `unknown`/`not_assessed` where evidence is absent. Keep performance rating separate from confidence. A crop label or botanical family must not determine a rating by itself. Seek an extension officer/agronomist and farmer review before calling rules locally validated; if no reviewer is available, label the rules provisional and constrain the demo claims accordingly.

## 5. Technical Questions and Recommendations

### 5.1 NASA POWER request and response handling

Use the NY-13 Daily Point contract with the approved coordinate(s), inclusive dates, `AG`, JSON, and explicit UTC. NASA POWER's daily API documents that it defaults to local solar time unless `time-standard=UTC` is requested, supports daily time series from 1981 to near real time, and returns each parameter at its original source resolution. NASA reports 2–3 day archive latency for meteorological data. Preserve actual returned units, fill value, source, coverage, and per-parameter resolution; do not present the point response as a station measurement.

Before freezing the DTO, run and archive a real response for a Product Owner-approved public demo/community point, then verify `PRECTOTCORR`, `T2M`, and `T2M_MAX` units, fill values, source products, and resolution. This exact validation cannot be completed from the research comments because no coordinate has been approved.

### 5.2 Snapshot identity and refresh

NY-13's reuse dimensions are appropriate for avoiding unnecessary external calls: provider/service, normalized parameter set, normalized location/grid identity, time standard, inclusive date range, units, adapter/schema version. Keep crop/season context associated with the use of a shared weather snapshot, not as a reason to duplicate an equivalent environmental response. Keep raw farm coordinates access-controlled and out of public diagnostics.

NASA documents 2–3 day meteorological archive latency, not a universal immutable-history guarantee. Recommended implementation policy: make freshness source-specific; treat the most recent latency window as potentially incomplete and refresh it after the provider's expected publication delay; do not impose an unexplained recurring TTL on older historical windows. Retain retrieval time and let an explicit refresh or documented source correction policy refresh older windows. If refresh fails, keep the valid prior snapshot and label it cached with its period and retrieval date. Confirm the precise policy with the Product Owner because freshness, API traffic, and user messaging trade off.

### 5.3 Missingness, sample data, and ranking

Keep missing values `null`/unavailable, preserve coverage counts, and do not impute or treat missing as zero. Do not silently redistribute criterion weights. The NY-16 suggestion to show a partial comparison or `insufficient_evidence` is safer than a definitive total when comparable evidence is absent. The numerical coverage threshold remains a product/agronomy decision; no evidence in NY-12–16 supports a particular percentage.

The PRD and NY-13 distinguish live, cached, and sample/demo data. In the current backend source, `DataStatus` in `backend/app/services/environmental_snapshots.py` and `IndicatorDataStatus` in `backend/app/indicators/environmental.py` contain `live`, `cached`, and `unavailable`, but not a separate `sample` state. Before exposing demo fixtures, decide whether `sample` becomes a distinct state or whether the persisted object carries a clear demo provenance field. Do not let “stored in Mongo” imply “live observation.”

### 5.4 Transparent MCDA and audit trail

Implement hard validity gates separately from ranking. Preserve per-criterion inputs, units, evidence/provenance, validation status, rating, confidence, rationale, weight profile, missing-data reason, ruleset/scoring versions, source IDs, NASA data state/coverage, and tie/sensitivity result. The OECD/JRC composite-indicator handbook emphasizes that weighting, aggregation, missing-data treatment, normalization, and sensitivity analysis affect results and should be assessed transparently. That supports NY-16's sensitivity and audit recommendations; it does **not** validate NovaYield's particular equal weights or crop ratings.

Prefer user-readable qualitative ratings for the MVP unless the Product Owner approves a numeric method and it is defined and disclosed. If ranking changes under plausible weights, label it weight-sensitive. If options remain tied after disclosed tie-breakers, show a tie rather than manufacturing a winner.

## 6. Product Owner Decisions Required

These choices are not settled by the PRD or external research. Recommendations are advice, not decisions made on the Product Owner's behalf.

### PO-1. Confirm pilot geography and demo location(s)

**Question:** Should NovaYield use Ejura-Sekyedumase Municipality as the first pilot, and which public/community reference point(s) should the demonstration use?

**Context:** NY-12 recommends Ejura-Sekyedumase provisionally and Kintampo South as fallback. The municipality has north–south variation, so one point could be misleading. No coordinates are approved in Jira.

**Options and implications:**

- Approve Ejura-Sekyedumase and select two representative community points: best supports the current evidence while showing within-municipality variation; needs local point validation.
- Approve Ejura-Sekyedumase but use one named point: simpler demo, weaker coverage of municipality variation.
- Select Kintampo South or another area: changes crop/season research and requires that area's validation.
- Defer exact point selection: implementation can use fixture contracts, but real-response validation and local calendar work remain blocked.

**Recommendation:** Approve Ejura-Sekyedumase provisionally and select at least two representative public/community points with extension input. Do not use precise farm coordinates in a public demo without a clear purpose and permission.

### PO-2. Approve the initial six candidate crops

**Question:** Should the MVP candidate library be maize, cowpea, groundnut, cassava, yam, and rice, as recommended by NY-14?

**Context:** The PRD requires 4–6 locally evidenced crops but only gives examples. The proposed six replace sorghum and soybean with yam and rice. Local authority and research sources support crop presence, but not all six crops' rule traits.

**Options and implications:**

- Approve NY-14's six as *candidate records*: aligns with local crop evidence while preserving provisional traits.
- Keep the PRD example list: simpler continuity, but soybean/sorghum local use still needs support and yam/rice evidence is omitted.
- Wait for extension/farmer review before locking six: strongest local validation, but delays library seeding and scoring integration.

**Recommendation:** Approve the six as candidate library entries only; do not equate inclusion with validated trait values or automatic recommendation eligibility.

### PO-3. Decide how the MVP handles unvalidated local season windows

**Question:** May the demo show provisional crop/community date windows, or should it withhold ranking until the local calendar is reviewed?

**Context:** The PRD requires a documented local calendar. NY-12/13 say calendars vary and must be validated. A provisional window can demonstrate data flow but may be mistaken for planting advice.

**Options and implications:**

- Show windows marked “provisional,” with source/date and no rule depending on them treated as validated: keeps the workflow demonstrable while making uncertainty explicit.
- Block generation/ranking until extension/farmer approval: safest interpretation, but limits the demo until validation is available.
- Use a broad municipality-wide season: quickest, but risks masking different systems and should not activate crop-specific hard rules.

**Recommendation:** Show provisional context only when clearly labelled, and keep crop/calendar-dependent rules and definitive ranking inactive until validated.

### PO-4. Choose the displayed NASA indicator set

**Question:** Should the MVP display two indicators or all three NY-13 candidates (seasonal precipitation total, mean T2M, and mean T2M_MAX)?

**Context:** PRD §4/FR-03 requires at least two and §15 asks which two or three are reliable. NY-13 proposes three; response metadata still needs confirmation.

**Options and implications:**

- Display all three after live metadata checks: richer temperature context and one shared data request; requires clear distinction between mean daily temperature and mean daily maximum.
- Display two (rainfall and mean T2M): simpler UI; leaves T2M_MAX out of comparison.
- Display two initially, retain T2M_MAX as an internal candidate: lower demo complexity, but requires later product review to expose it.

**Recommendation:** Use all three if the approved-location response confirms units/coverage and the UI can explain them plainly; otherwise launch with the reliable two and document why.

### PO-5. Approve the default weights and farmer-priority interaction

**Question:** Should equal 25% weights be the disclosed default, and how should farmers change priorities?

**Context:** The PRD requires priorities to affect weights but does not prescribe equal weights or an input control. NY-16's 25/25/25/25 is explicitly a placeholder, not an agronomic optimum.

**Options and implications:**

- Equal 25% default plus 100 importance points/sliders: simple starting point with meaningful farmer influence; needs explanation and a saved weight profile.
- Product-defined default weights: can reflect a project emphasis, but are still assumptions and require justification/visibility.
- Discrete priority choices that map transparently to normalized weights: potentially easier on mobile, but mapping must be shown and tested.

**Recommendation:** Equal default is the least opinionated starting point; allow a simple, visible farmer adjustment and label all weights provisional. Treat “non-negotiable” preferences as hard constraints only after the farmer condition and rule evidence are confirmed.

### PO-6. Set the minimum evidence rule for an overall rank

**Question:** When ratings are missing or incomparable, should NovaYield show a partial comparison, or withhold an overall ranking? What evidence coverage is enough?

**Context:** Neither NY-13 nor NY-16 supplies a validated coverage threshold. Missing criteria cannot safely become zero or a midpoint.

**Options and implications:**

- Require comparable evidence on all four criteria for every option before an overall rank: strongest guard against false comparison, but likely to yield `insufficient_evidence` frequently at first.
- Show per-criterion comparison and withhold only the total when a criterion is missing/incomparable: preserves useful information without claiming a definitive winner.
- Approve a minimum number/percentage of assessed criteria: permits more ranks but creates a policy threshold requiring agronomy/product justification.

**Recommendation:** Show partial criterion comparisons; withhold definitive overall ranking where evidence is missing or not comparable. Do not set a numeric threshold until the agronomist/product review identifies a defensible rule.

### PO-7. Decide rating presentation and sensitivity scenarios

**Question:** Should the MVP use qualitative High/Moderate/Low ratings or numeric criterion scores, and how many alternative weight profiles should users see?

**Context:** PRD allows either visible component scores or Low/Medium/High, while warning against false precision. NY-16 asks for sensitivity and an explicit number of comparison profiles.

**Options and implications:**

- Qualitative labels plus criterion breakdown and equal-vs-farmer-weight sensitivity: explainable, though evidence categories need review criteria.
- Numeric ordinal scores with published mapping: easier to sort, but can imply more precision than evidence supports.
- Offer several weight presets: may help exploration but adds UI and validation scope.

**Recommendation:** Use qualitative ratings in the initial demo. At minimum, explain the equal-weight result versus the farmer-selected profile; flag any rank change as weight-sensitive. Do not add preset profiles until user testing shows a need.

### PO-8. Approve recent-data refresh and freshness messaging

**Question:** Should NovaYield refresh near-real-time POWER requests after NASA's documented meteorological latency, and how should older historical snapshots be refreshed?

**Context:** NASA reports 2–3 day latency for meteorological data but does not provide a universal immutability guarantee for historical series. NY-13 leaves freshness policy open; current snapshot policy has no default refresh interval.

**Options and implications:**

- Source-specific refresh for recent windows after the expected latency; no arbitrary TTL for older history, with explicit refresh available: balances currentness and API reuse.
- Refresh every request: most current when available, but defeats reuse and can create redundant upstream calls.
- Fixed TTL for every request: simple but unsupported by the cited source cadence and can trigger unnecessary refreshes.

**Recommendation:** Prefer source-specific handling: refresh recent windows after the documented delay; reuse older exact-identity historical snapshots unless a documented correction policy or explicit refresh applies. Always preserve a valid cached copy if refresh fails, and show period/retrieval date/status.

### PO-9. Secure an agronomy/extension reviewer

**Question:** Can the Product Owner arrange a municipal extension officer, agronomist, or knowledgeable local advisor to review the crop list, calendar, and rule assumptions?

**Context:** The PRD identifies the absence of a dedicated agronomist/GIS specialist as a validation risk and asks for an advisor if possible. NY-12/14/15 depend on local confirmation.

**Options and implications:**

- Arrange review before activating crop/calendar rules: strongest validation path; needs stakeholder time.
- Proceed with desk research only: lets prototype work continue, but all agronomic rules must remain explicitly provisional and claims limited.
- Validate only the pilot/crops used in the demo: narrows effort but leaves other candidate records inactive.

**Recommendation:** Seek review for the chosen pilot, initial crop records, major/minor calendar, rice water system, residue practices, and any proposed hard rule. If unavailable, keep the limitations visible and do not call the rules validated.

## 7. Implementation Implications

1. **Phase 0 — decisions and validation:** Confirm pilot geography/points, crop set, indicator set, local season source/version, and whether an advisor can review the assumptions. Keep those decisions in a versioned research record.
2. **Phase 1 — data contract:** Request `PRECTOTCORR`, `T2M`, and `T2M_MAX` in UTC from the approved point; verify actual metadata; keep raw values, fill/missingness, source, units, resolution, period, and retrieval provenance together. Keep any sample/demo dataset distinguishable from live-derived cache.
3. **Phase 2 — crop/plot model:** Store candidate crops with evidence/validation states. Represent planting events by plot and locally defined season, not calendar year. Record system-specific information such as rice ecology and residue handling when required by a rule.
4. **Phase 3 — rules:** Implement data-integrity gates and `needs_review` behavior first. Keep provisional agronomic rules as warnings/research notes; only approved, scoped rules may exclude a sequence.
5. **Phase 4 — scoring:** Apply hard constraints before ranking. Preserve four criteria from PRD FR-06. Carry missingness as `not_assessed`, not zero; preserve confidence separately from rating. Save weights, criteria explanations, rule version, and data state. Do not rank if the approved evidence policy says comparability is insufficient.
6. **Phase 5 — user explanation:** Show the source/date window, live/cached/sample status, per-indicator coverage, grid limitations, provisional calendars, assumptions, criteria/weights, benefit, trade-off, and reasons for exclusions/rank. A change in input/priority must reproduce an explainable change.
7. **Validation before “done”:** Run a real NASA response at approved point(s); compare with suitable local/GMet records if accessible; review crop/calendar/rules with local expertise; exercise missing/partial/live/cached/sample fallback cases; and check that no output claims field-level measurement or validated yield.

**Research-ticket dependencies in Jira:** NY-12 blocks NY-14 and NY-15; NY-13 blocks NY-5, NY-6, NY-7, and NY-16; NY-14/NY-15 also block NY-16 and the implementation/handoff tickets shown on Jira. The intended flow is therefore pilot/context → crop and rule research (with NASA data specification progressing in parallel) → comparison/scoring framework → implementation handoff. Avoid treating the Jira link graph as evidence that research has been field-validated.

**Tracking note:** All five Jira issues currently display In Progress. NY-16's comment specifically requests To Do until the Product Owner approves weights/evidence and upstream NY-13/14/15 validation; this mismatch should be reconciled by the team separately. This review did not edit Jira.

## 8. References

### Jira and project requirements

- [NY-12 — Recommend a Ghanaian pilot agroecological area](https://devbysam.atlassian.net/browse/NY-12) — one comment, research brief dated 24 October 2026.
- [NY-13 — Define NASA POWER data and indicator specifications](https://devbysam.atlassian.net/browse/NY-13) — one comment, specification v1.0.
- [NY-14 — Select a locally grounded 4–6 crop MVP library](https://devbysam.atlassian.net/browse/NY-14) — one comment, provisional crop library v1.0.
- [NY-15 — Document evidence-backed crop-rotation constraints and rules](https://devbysam.atlassian.net/browse/NY-15) — one comment, conservative rule specification v1.0.
- [NY-16 — Define the transparent MVP comparison and scoring framework](https://devbysam.atlassian.net/browse/NY-16) — one comment, provisional comparison framework v1.0.
- *NovaYield MVP PRD*, version 1.0, “Refined Hackathon MVP,” dated 15 October 2026, status “Draft for team alignment.” PRD sections referenced above: §§1–17 and Appendix A; tables include P0/P1 capabilities, FR-01–FR-11, scoring criteria, entities, non-functional requirements, validation, risks, and delivery sequence.

### Ghana agriculture, calendars, and local evidence

- Ejura-Sekyedumase Municipal Assembly, [Town Profile](https://esma.gov.gh/about-us/town-profile/) — municipal north/south vegetation, rainfall pattern, and crop context.
- Ejura-Sekyedumase Municipal Assembly, [2024 Composite Budget](https://esma.gov.gh/wp-content/uploads/2022/11/ESMA-Composite-budget-2024.pdf) — current municipal crop/economic context; do not treat a budget as a crop calendar.
- Ghana Ministry of Food and Agriculture, [Ejura-Sekyedumase District Directorate profile](https://mofa.gov.gh/site/sports/district-directorates/ashanti-region/164-ejura-sekyeredumase) — crops, soils, and broad season information; older production figures need caution.
- Ghana Ministry of Food and Agriculture, [Guide to Maize Production](https://www.mofa.gov.gh/site/images/pdf/production_guides/GUIDE_TO_MAIZE_PRODUCTION.pdf) — planting timing varies with agroecology/season/variety and should use local weather information.
- Ghana Meteorological Agency, [Agrometeorological Services](https://www.meteo.gov.gh/Services/agrometeorology/) — seasonal forecasts, onset/cessation, dry spells, rainfall and temperature products for agriculture.
- Ghana Meteorological Agency, [Seasonal Forecast SON 2026](https://www.meteo.gov.gh/product/seasonal-forecast/seasonal-forecast-son-2026/) — current seasonal forecast; use as a forecast, not a permanent crop calendar.
- Obour, Arthur & Owusu (2022), [“The 2020 Maize Production Failure in Ghana: A Case Study of Ejura-Sekyedumase Municipality”](https://www.mdpi.com/2071-1050/14/6/3514), *Sustainability* 14(6), 3514 — local one-season case study based on farmer/key-informant evidence and meteorological data.
- Adjei-Nsiah et al. (2008), [“Farmers’ agronomic and social evaluation of productivity, yield and N₂-fixation in different cowpea varieties and their subsequent residual N effects on a succeeding maize crop”](https://link.springer.com/article/10.1007/s10705-007-9133-3), *Nutrient Cycling in Agroecosystems* 80:199–209 — Ghana transition-zone variety and residue context; not a universal crop credit.
- Daramy (2015), [KNUST thesis on cowpea fertilizer response and residual effects on succeeding maize](https://ir.knust.edu.gh/handle/123456789/8461) — KNUST 2014 field experiments; the repository abstract reports no significant residual fertilization effect in that trial.
- Nyalemegbe & Osakpa (2012), [“Rotation of maize with some leguminous food crops for sustainable production on the vertisols of the Accra Plains of Ghana”](https://ugspace.ug.edu.gh/items/d346fb22-09de-4507-9c62-3d1c55e91c7e), *West African Journal of Applied Ecology* 20(2) — Ghana field study with residue/legume-specific maize responses; Accra Plains conditions are not Ejura.
- Ghana Rice Development Strategy, [rice production system document](https://riceforafrica.net/wp-content/uploads/2021/09/ghana_en.pdf) — distinguishes rain-fed upland, rain-fed lowland, and irrigated ecologies.
- FAO, [Crop Calendar](https://cropcalendar.apps.fao.org/?isocode=GHA) — country/crop/agroecological calendar resource; verify pilot-specific applicability with local extension.
- Kusi et al. (2024), [Northern Ghana field study on insecticide/intercropping and fall armyworm in maize](https://www.sciencedirect.com/science/article/pii/S0261219424003375), *Crop Protection* 186 — adjacent intercropping evidence from a different ecology; it does not establish a rotation break interval for Ejura.

### NASA POWER and data interpretation

- NASA POWER, [Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) — point request parameters, formats, time standards, and parameter-specific source resolutions.
- NASA POWER, [Data FAQs](https://power.larc.nasa.gov/docs/faqs/data/) — source resolution, data sources, temporal processing, and reported latency.
- NASA POWER, [Temporal data processing](https://power.larc.nasa.gov/docs/methodology/data/processing/) — hierarchy of hourly, daily, monthly, and derived daily values.
- NASA POWER, [Validation API](https://power.larc.nasa.gov/docs/services/api/validate/) — available validation/comparison products; local station suitability must still be established.
- ISRIC SoilGrids, [FAQ](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs.html) and [layers/uncertainty documentation](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html) — 250 m modeled soil-property predictions, depths, quantiles, and uncertainty.

### Decision-analysis method

- OECD / European Union / European Commission Joint Research Centre (2008), [Handbook on Constructing Composite Indicators](https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators-methodology-and-user-guide_9789264043466-en.html) — general guidance on weighting, aggregation, missing data, and uncertainty/sensitivity analysis. It supports transparent method review, not NovaYield-specific weights.
