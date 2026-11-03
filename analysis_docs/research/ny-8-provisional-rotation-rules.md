# NY-8 Provisional Agronomic Rotation Rules

**Status:** Desk-research rule proposal; provisional for Ejura and subject to future local/agronomist validation.  
**Version:** 0.1  
**Purpose:** Turn the reviewed evidence into conservative, explainable rules for selecting up to four rotation options when the required evidence is comparable.

This document is a research synthesis, not a claim that I am a credentialed agronomist or that these rules have been field-validated. The evidence and its transfer limits are cited below. A Product Owner decision on 3 November 2026 removes labour feasibility from rotation scoring. This rule proposal retains the other three PRD criteria: water resilience, soil-health potential, and yield-stability proxy.

## 1. Decisions and boundaries

- Score three criteria only: **water resilience**, **soil-health potential**, and **yield-stability proxy**. Do not collect, return, weight, or rank on labour feasibility.
- Preserve the previously approved equal-weight approach across the remaining criteria. **Implementation interpretation:** normalize the equal defaults to one third each (33.3333…%); let the farmer adjust only these three priorities.
- Keep the approved missing-evidence policy: show supported criterion-level information, but withhold an overall rank when an option lacks comparable evidence for any required criterion. Do not turn `unknown` into a neutral or poor rating.
- Apply hard exclusions before comparing options. A farmer priority cannot override an evidence-backed hard constraint.
- Generate candidates internally as needed, but return at most the **top four ranked alternatives**. If known current practice is supplied, include it as a separately labelled baseline comparator; do not silently call it a recommended alternative.
- Historical NASA periods describe past conditions. They are not a forecast for future recommendation seasons. Use past climate only as context for recurring local variability and clearly state the period/source.
- Climate variability is a condition to adapt to, not a hard filter by itself. Do not claim to control or predict climate change. Do not invent a future-weather outlook.

The one-third default is an implementation interpretation of the prior equal-weight decision after removing a fourth criterion; it is not an agronomic finding. The removal of labour feasibility is an explicit MVP scope change from the four-criterion comparison in the original PRD and should be reflected in API/UI contracts and the PRD revision when those are next updated.

## 2. Evidence that can inform the rules

| Crop | Evidence usable as a provisional rule input | How to use it safely | Main limit |
| --- | --- | --- | --- |
| Maize | FAO gives an indicative total crop water need of 500–800 mm and medium-high drought sensitivity. Ghana rotation studies report improved maize outcomes after particular legume treatments. | Treat as a relatively water-sensitive cereal; consider a preceding cowpea/groundnut only under the soil/residue rule below. | Generic crop-water range; variety, duration, season, soil, and actual water supply are not represented. Legume effects depend on treatment and site. |
| Cowpea | Ghana trials identify drought response and yield differences among genotypes and environments. | Keep water response unknown unless an identified variety has relevant evidence. Do not give a generic cowpea bonus or water-demand number. | Crop name alone does not identify variety or response; drought-sensitive stages still matter. |
| Groundnut | FAO gives an indicative 500–700 mm total-period water need and low-medium drought sensitivity. Ghana trials show accession and environment effects. | Use only as broad water-risk context, and only when crop duration and production system are comparable. | Not an Ejura-specific water balance or a rating for an unspecified variety. |
| Cassava | FAO describes prolonged-drought tolerance after establishment, with sensitivity to soil-water deficit during the first three months after planting. | Treat establishment-window water as a distinct risk; do not label cassava simply “low water” or drought-proof. | Variety, establishment date, soil moisture, and crop duration matter; no comparable seasonal water-demand value is established here. |
| Yam | The reviewed sources do not provide a comparable pilot-specific water-demand or drought-response rating. | Keep water rating `not_assessed` until a sourced, matching variety/calendar/system value is available. | No basis for ranking yam's water resilience against other candidates. |
| Rice | FAO's 450–700 mm and high drought sensitivity apply to **paddy rice**. Ghana sources distinguish upland, lowland, and irrigated systems. | Require the rice production system and water access before using paddy evidence. | The paddy estimate must not be assigned to upland or rain-fed lowland rice. |

FAO explicitly presents its crop-water figures as rough estimates dependent on growing-period length and climate. Crop water need (evapotranspiration) is not the same as rainfall requirement. Seasonal NASA precipitation alone does not account for effective rainfall, runoff, stored soil water, irrigation, or crop evapotranspiration. Therefore, do not subtract the FAO range from NASA rainfall and call the result a measured crop deficit. `T2M` and `T2M_MAX` describe historical air-temperature conditions, not crop canopy temperature or a validated crop heat-stress threshold; they must not independently trigger a crop exclusion.

## 3. Rule set

| Rule ID | Rule | Effect | Required inputs and missing-data behavior | Evidence/status |
| --- | --- | --- | --- | --- |
| NY8-DATA-01 | A rotation consists of exactly three chronological planting events on the same plot. | Hard data-integrity gate. Reject malformed sequences before scoring. | Three events, plot identity, order, non-overlapping event windows. Invalid/missing event structure cannot be ranked. | NY-15; high confidence as a data-integrity rule. |
| NY8-DATA-02 | Use only approved candidate crops and preserve a known farmer-reported baseline as a comparator. | Hard data-integrity gate. Do not invent history or baseline crops. | Candidate-library membership and provenance for reported history. Unknown history is `needs_review`, not an assumed fallow or crop. | NY-14/NY-15; high confidence for data integrity. |
| NY8-CAL-01 | A crop assigned to a planting event must match a sourced crop/community planting window before calendar-dependent suitability is scored. | Hard gate only after the calendar is locally validated; otherwise mark `needs_review` and withhold a definitive rank. | Crop, variety where known, community, season, calendar source/version. Provisional windows remain visibly provisional. | PO Decision 3 and NY-15; local windows remain provisional. |
| NY8-WAT-01 | Compare water fit only when the crop trait, production system, event window, and farm water context are sufficiently matched. | Criterion assessment, not a blanket crop exclusion. A sequence with unknown crop or water-system evidence has water status `not_assessed`. | Crop/variety, crop duration or stage window, rice ecology if relevant, irrigation/water access, and comparable period-specific climate evidence. | FAO crop-water guidance; NY-13; provisional. |
| NY8-WAT-02 | In a documented water-limited context, prefer a sequence with better-supported lower drought sensitivity over a more sensitive alternative, all else comparable. | Relative water-resilience comparison; never a guaranteed yield or water-sufficiency claim. | A documented water-limited context and comparable crop-response evidence. If context or one option's trait is unknown, do not assign a comparative rating. | FAO: maize medium-high, groundnut low-medium, paddy rice high; Ghana cowpea results are genotype-dependent; cassava is stage-dependent. Provisional. |
| NY8-WAT-03 | Do not apply paddy-rice water rules to rice unless the farm's rice ecology is identified. | `needs_review`; do not infer a rice system from the crop name. | Upland, rain-fed lowland, or irrigated classification and water-access details. | Ghana rice strategy and Tono irrigation study; scope-specific. |
| NY8-SOIL-01 | A cowpea- or groundnut-before-maize sequence may receive a provisional soil-health-potential preference only when residue/biomass management and study context support the comparison. | Soft, criterion-level preference; never a nitrogen credit, measured soil-health claim, or hard sequence rule. | Ordered crop events, residue fate/retention, relevant variety/management evidence. If residue fate is unknown, explain the possible relationship but leave the rating `not_assessed`. | Kermah et al. (2019), Nyalemegbe et al. (2012); specific treatments/sites, limited transfer to Ejura. |
| NY8-SOIL-02 | Do not award a soil benefit merely because a crop is a legume. | Prevent unsupported scoring. | Evidence of relevant biomass/residue contribution and management. Missing evidence means no score. | NY-14/NY-15 and Ghana rotation studies; high confidence that a blanket credit is unsupported. |
| NY8-STAB-01 | Rate yield-stability proxy only from comparable multi-season evidence for the relevant crop/variety/sequence and environment. | Otherwise `not_assessed`; no overall rank while required evidence is missing. | Same outcome definition, relevant location/environment, variety/system, and comparable multi-season sequence results. | NY-8 evidence matrix; current evidence is not comparable across all six crops/sequences. |
| NY8-CLIM-01 | Use historical climate variability to explain exposure and trade-offs; do not treat a past season as a future forecast or climate change as an automatic exclusion. | Context/explanation only unless a validated rule links it to a crop/event. | Source, historical period, location/grid limitations, and clear past-vs-future labels. | NY-13, NY-17 handoff, and NASA POWER limitations. |
| NY8-RANK-01 | Apply hard constraints first, then rank only candidates assessed on all three criteria using the same comparison basis. Return no more than four ranked alternatives. | Rank top four when evidence is complete and comparable; otherwise return supported partial comparisons and `withheld` ranking with reasons. | Three comparable criterion assessments per option, weights, rule version, provenance, and baseline where known. | Existing PO Decision 6 remains in force. |

## 4. Provisional water interpretation for the pilot

The sources justify **relative caution**, not exact crop-by-crop water scores:

1. Maize's broad water-need range and medium-high drought sensitivity make it a higher-concern choice when a planting window is documented as water-limited.
2. Groundnut's broad range is similar in magnitude, but FAO reports lower drought sensitivity. This does not prove groundnut is the better crop for a particular Ejura field or variety.
3. Cassava may tolerate prolonged drought after establishment, but a dry first three months can undermine establishment. The crop's long duration means it cannot be compared by seasonal rainfall total alone.
4. Cowpea should not be assigned a universal drought rating. Ghana studies show substantial genotype/environment differences; named variety evidence is needed.
5. Paddy rice is water-sensitive; without the production system and dependable water-access information, a rice sequence remains `needs_review` for water comparison.
6. Yam remains unscored for water until comparable evidence is found.

For these reasons, NASA `PRECTOTCORR`, `T2M`, and `T2M_MAX` are environmental context, not enough by themselves to prove water sufficiency. An eventual water-risk feature should use a documented historical baseline for the same community/season and a reviewed crop window, and must label the result as historical context. It must not claim to forecast the upcoming planting event.

## 5. Ranking and top-four behavior

1. Generate candidate sequences deterministically; apply only the hard data/calendar/validated agronomic constraints.
2. Assess water resilience, soil-health potential, and yield-stability proxy independently, preserving source, confidence, assumptions, and missingness for each.
3. Normalize the three default priorities equally (one third each); normalize farmer-selected priorities across the same three criteria.
4. Rank only when all compared non-excluded alternatives have a rating for all three criteria on comparable bases. Use the existing deterministic tie behavior and expose weights/rationale, not an invented probability or precise yield score.
5. Return at most four alternatives. If evidence does not support four ranked alternatives, return fewer or withhold the overall rank; do not pad the list with unsupported sequences. Include a known baseline as a clearly identified comparator.

**Current demo-profile result:** The Ejura area archetype does not yet support even one overall rank. It has no validated crop calendar, named varieties, plot-level water access, rice ecology, residue history, or comparable multi-season sequence evidence. The three criteria remain `not_assessed` or incomplete for cross-option comparison. Removing labour eliminates one criterion but does not make a top-four ranking evidence-ready. Under PO Decision 6, the correct current output is a withheld overall rank with transparent reasons.

## 6. Evidence references

- FAO, [Crop Water Needs, Chapter 3](https://www.fao.org/4/S2022E/s2022e07.htm): indicative total-period needs and drought sensitivity for maize, peanut/groundnut, and paddy rice; rough estimates dependent on crop duration and climate.
- FAO, [Save and Grow: Cassava](https://www.fao.org/4/i3278e/i3278e.pdf): cassava drought response and first-three-month establishment sensitivity.
- Mustapha (2017), University of Ghana, [Genetic variability for drought tolerance in cowpea in Ghana](https://ugspace.ug.edu.gh/items/6ca7b2cc-9533-4d3b-9922-cf4589f3a914): genotype and environment effects across Ghana ecologies.
- Kermah et al. (2019), [Legume-maize rotation or relay options in northern Ghana](https://pure.ug.edu.gh/en/publications/legume-maize-rotation-or-relay-options-for-ecological-intensifica-2/), DOI [10.1017/S0014479718000273](https://doi.org/10.1017/S0014479718000273): crop/soil/treatment-specific rotation evidence.
- Nyalemegbe et al. (2012), [Rotation of maize with leguminous food crops on Ghanaian Vertisols](https://ugspace.ug.edu.gh/items/d346fb22-09de-4507-9c62-3d1c55e91c7e): named varieties, residue treatments, and succeeding-maize outcomes at Kpong.
- NY-8, [Provisional crop-by-criterion evidence matrix](ny-8-crop-criterion-evidence-matrix.md): full source confidence, limitations, and current ranking-readiness status.
- NY-8, [Public demo area archetype](ny-8-public-demo-profile.md): location/context evidence and explicit unknowns.
