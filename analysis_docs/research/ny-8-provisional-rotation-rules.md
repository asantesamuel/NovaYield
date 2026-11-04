# NY-8 Provisional Four-Criterion Rotation Policy

**Status:** Product Owner approved implementation policy; crop ratings and all agronomic interpretation remain provisional until local review.

**Version:** 0.3

**Updated:** 4 November 2026

**Purpose:** Define a transparent, farmer-prioritized method that returns up to three options only when all four criteria have comparable evidence; never fill missing evidence or claim validated farm advice.

This is a documented research synthesis and software rule set, not a claim of personal agronomy credentials or local field validation. The public-data Ejura profile is an area archetype, not a real farm.

## 1. Product decision and scope

- **Active criteria:** water resilience, soil-health potential, yield-stability proxy, and labour feasibility. Ratings remain provisional and evidence-scoped.
- **Weights:** use equal 25% weights when no priorities are saved. Normalize farmer-entered 0–100 priority points to percentages when preferences exist. Weights may change the order but never override a hard constraint.
- **Ordinal scoring implementation choice:** map High/Moderate/Low to 3/2/1 and calculate a weighted sum. This assumes equal spacing between qualitative categories. It is compensatory: gains on a high-weight criterion can offset weaker ratings elsewhere. It is not a probability or measured outcome.
- **Missing evidence:** every alternative must have all four criteria assessed on comparable bases. Otherwise withhold the overall ranking; do not impute, use a neutral value, or redistribute weights. Preserve the available criterion findings and state which evidence is missing.
- **Current data consequence:** the water class is provisional, while soil, sequence-level yield stability, and farm-specific labour feasibility lack comparable evidence/inputs. The current real workflow is therefore expected to withhold a rank until those gaps are addressed.
- **Output limit:** return at most the **top three** alternatives. This matches NY-8's original requirement for three options. There is no NY-8 requirement for four; the earlier “top four” wording was an implementation/documentation mistake and is superseded.
- If a known farmer-reported current practice exists, return it in a separate `baseline_option`, not as one of the three alternatives.
- Preserve a tied group. Within ties, use candidate ID only for stable display order; do not prefer more diverse sequences. If the three-item limit cuts through a tie, disclose that equally ranked options were omitted from the short list.
- Missing or incomparable evidence in any active criterion leaves the overall ranking withheld; do not return a partial rank based on only the criteria that happen to be available. Do not impute or replace missing values.
- Apply evidence-backed hard constraints before ranking. A review-needed calendar or crop suitability remains visible as a provisional warning; it does not become a fabricated pass or fail. Results are explicitly labelled provisional.
- Historical NASA POWER indicators remain attached for traceability, but do not adjust the crop-level class or predict future recommendation seasons.

Return the default equal-weight ranking and selected-priority ranking, normalized weights, sensitivity status, and criterion-level trade-offs. Keep a separate known baseline, return no more than three alternatives, and preserve ties with candidate-ID display order only. Review-needed calendar and suitability warnings remain visible; provisional results are not locally validated.

## 2. Water evidence table used by NY-8 v3

“High” means relatively stronger resilience to water stress within this provisional candidate set, not low water consumption. The underlying sources use different crops, settings, and methods, so the categories are deliberately coarse, confidence is shown separately, and all results remain provisional.

| Crop | Provisional water class | Confidence | Evidence and reason | Key limitation |
| --- | --- | --- | --- | --- |
| Groundnut | High | Low | FAO gives an indicative 500–700 mm per growing period and low-to-medium drought sensitivity. | Generic range; variety, duration, soil, and Ejura transfer are unknown. |
| Cowpea | Moderate | Low | A Ghana Tono irrigation study supplies water-use context; Ghana trials show drought response varies by genotype/environment, so no universal high rating is justified. | Irrigated Tono and tested genotypes may not represent Ejura rain-fed farms. |
| Cassava | Moderate | Moderate | FAO describes drought tolerance after establishment but sensitivity to water deficit during the first three months. The unresolved establishment window prevents a high class. | Variety, planting date, early-season soil moisture, and field management are unknown. |
| Maize | Low | Moderate | FAO gives an indicative 500–800 mm per growing period and medium-to-high drought sensitivity. | Generic range, not a local forecast or a crop failure probability. |
| Yam | Low | Low | A West African production review describes a long crop duration and need for sufficient, well-distributed moisture. | Broad regional evidence; local variety/calendar and field water storage are unknown. |
| Rice | Not assessed | — | No rating until the production system is identified. FAO paddy figures must not be applied to upland rice. | Upland, lowland, and irrigated ecologies are not interchangeable. |

Sources: [FAO crop water needs](https://www.fao.org/4/S2022E/s2022e07.htm), [FAO Save and Grow: Cassava](https://www.fao.org/4/i3278e/i3278e.pdf), [Ghana Tono water-use study](https://cspace.csirgh.com/items/show/1466), [Ghana cowpea drought variation study](https://ugspace.ug.edu.gh/items/6ca7b2cc-9533-4d3b-9922-cf4589f3a914), and [West African yam production review](https://doi.org/10.5772/intechopen.106504).

### Sequence rule

For each three-season sequence, use the **least water-resilient rated crop** as the sequence's water class. This conservative bottleneck rule avoids averaging away a vulnerable season. It is an implementation choice, not a validated agronomic threshold. If any crop is not assessed (currently rice with unknown ecology), the sequence water criterion is `not_assessed` and it cannot be ranked.

Do not interpret this class as crop water requirement. FAO defines crop evapotranspiration using reference evapotranspiration and a crop coefficient (`ETc = ETo × Kc`); crop stage, climate, and growing-period length matter. The current NASA POWER inputs are historical precipitation and temperature only. They do not include all required water-balance inputs such as humidity, wind, radiation, effective rainfall, irrigation delivery, soil storage, or the matching crop-stage coefficients. Therefore NASA values are provenance/context in the result, not a quantity used to assign crop class.

## 3. Soil-health evidence status

Ghana field research supports specific legume/fallow/residue relationships before maize under named treatments; it does not support a universal soil benefit for every legume or sequence. Soil-health effects depend on biomass, variety, residue fate, soil, and management. The current farm/result inputs do not capture enough of that context. Therefore:

1. Current NY-8 v3 emits soil-health potential as `not_assessed` because comparable sequence evidence and required management inputs are missing.
2. A sourced assessment requires sequence-level evidence and relevant soil/residue/management context.
3. Missing soil evidence blocks the four-criterion overall ranking; it is not a neutral rating and does not receive redistributed weight.
4. Never describe a potential as measured soil health, nitrogen credit, or guaranteed yield improvement.

Relevant research includes [Ghana cowpea/legume–maize rotation work](https://doi.org/10.1017/S0014479718000273) and [maize rotations with food legumes on Ghanaian Vertisols](https://ugspace.ug.edu.gh/items/d346fb22-09de-4507-9c62-3d1c55e91c7e); results are treatment- and site-specific.

## 4. Ranking steps and response behavior

1. Generate three-event sequences deterministically. Keep known current practice as a separate baseline. Repeated crops remain candidates with ROT-004 review warnings unless an approved hard rule says otherwise.
2. Apply explicitly failed hard constraints before assessment; farmer priorities cannot override them. Preserve `needs_review` warnings.
3. Build records for all four criteria with status, rating when supported, confidence, rationale, comparison basis, citations, assumptions, and relevant NASA inputs. NY-13 requires at least two usable approved NASA indicators in each past analysis period; partial coverage is retained and no percentage threshold is invented.
4. Require each compared alternative to have all four criteria assessed on one common comparison basis per criterion. If any criterion is missing or incomparable for any alternative, withhold ranking and do not redistribute its weight.
5. Normalize saved priority points to percentages; if none exist, use equal weights. Compare both the equal-weight and selected-priority views and report whether the shortlist changes.
6. Explain the selected ranking with criterion ratings, weights, pairwise gains/concessions, and any tie at the three-item display limit. Candidate ID is stable display order only.
7. Return at most three alternatives and the baseline separately, plus pool counts, status, versions, criterion provenance, NASA snapshot references, and tie/withholding reasons.

The generator may examine 216 combinations from six crops internally. The API result's `scoring_result.options` contains no more than three alternatives; pool counts may appear as audit provenance. The returned list is not a prediction and does not imply that a displayed tied option is strictly better than another tied option. NY-13's existing minimum of two usable indicators in each past period is required before the primary water criterion can be assessed; partial indicators retain their coverage and no new coverage threshold is invented.

## 5. Evidence and weighting trade-offs

Multi-criteria research distinguishes compensatory methods (one criterion can offset another) from non-compensatory methods. NovaYield now uses a compensatory weighted ordinal sum because the Product Owner wants farmer priorities to affect order. The weights make the trade-off visible, but do not make weak evidence stronger. Evidence-strength MCDA recognizes incomparability when evidence cannot support a distinction; NovaYield therefore withholds when any active criterion is missing or incomparable instead of filling a rating or reweighting the remainder.

Four criteria can better reflect different farmer priorities only when all four ratings are supported and comparable. With current research, the scorer will report available evidence and withhold a real ranking. Soil and yield findings are sequence/variety/context-specific; labour feasibility additionally needs farm area, labour availability, operation timing, and machinery/service access. Rice remains unassessed until its production ecology is known. Local validation remains required before describing any result as agronomic advice.

## References

- FAO, [Crop Water Needs, Chapter 3](https://www.fao.org/4/S2022E/s2022e07.htm): indicative needs/sensitivity; `ETc = ETo × Kc`; values depend on growing period and climate.
- FAO, [Save and Grow: Cassava](https://www.fao.org/4/i3278e/i3278e.pdf): drought response after establishment and first-three-month sensitivity.
- Asaana et al., [Water-use assessment at Tono Irrigation Scheme, Ghana](https://cspace.csirgh.com/items/show/1466): study-specific crop water-use context.
- Mustapha, University of Ghana, [Genetic variability for drought tolerance in cowpea in Ghana](https://ugspace.ug.edu.gh/items/6ca7b2cc-9533-4d3b-9922-cf4589f3a914): genotype/environment effects.
- West African production review, [Water needs and yam crop duration](https://doi.org/10.5772/intechopen.106504): broad yam context; limited pilot transferability.
- Adiku et al., [Crop rotation and residue management in Ghana's forest–savannah transition](https://ugspace.ug.edu.gh/items/7526f19b-7322-4be3-9863-ed349b390137): site/treatment-specific maize, residue, and soil-carbon results.
- Martin et al., [Strength-of-evidence MCDA](https://pmc.ncbi.nlm.nih.gov/articles/PMC8193858/): incomplete evidence can warrant incomparability rather than a forced preference.
- da Silva et al., [Lexicographic criteria ordering in MCDA](https://onlinelibrary.wiley.com/doi/10.1155/2015/481950): criteria are ordered by decision-maker importance; a non-compensatory method is available when that order is explicit.
- FAO, [Crop evapotranspiration guidelines](https://www.fao.org/4/x0490e/x0490e0a.htm): ETc depends on reference ET and crop coefficient/stage.
- NovaYield, [NY-8 public-data profile](ny-8-public-demo-profile.md) and [crop evidence matrix](ny-8-crop-criterion-evidence-matrix.md): area archetype and crop-specific evidence limits.
