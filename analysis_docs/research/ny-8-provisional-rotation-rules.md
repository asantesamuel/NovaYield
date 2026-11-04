# NY-8 Provisional Water-First Rotation Policy

**Status:** Product Owner approved implementation policy; crop ratings and all agronomic interpretation remain provisional until local review.

**Version:** 0.2

**Updated:** 3 November 2026

**Purpose:** Define a transparent method that returns up to three water-first options without filling missing evidence or claiming validated farm advice.

This is a documented research synthesis and software rule set, not a claim of personal agronomy credentials or local field validation. The public-data Ejura profile is an area archetype, not a real farm.

## 1. Product decision and scope

- **Primary criterion:** relative crop water-stress resilience, represented as High / Moderate / Low. The rating is a desk-researched crop-level proxy; it is not an estimate of litres, irrigation need, water sufficiency, yield, or future weather.
- **Optional secondary criterion:** soil-health potential may break a tie between options with the same water rank only when every option in that tied group has assessed soil evidence on the same comparison basis. Missing soil evidence leaves the water tie intact.
- **Not scored:** yield-stability proxy and labour feasibility are omitted from this ranking version. Farmer-entered priority points do not change the fixed water-first order. Historic farm/result records may still contain those legacy fields.
- **Output limit:** return at most the **top three** alternatives. This matches NY-8's original requirement for three options. There is no NY-8 requirement for four; the earlier “top four” wording was an implementation/documentation mistake and is superseded.
- If a known farmer-reported current practice exists, return it in a separate `baseline_option`, not as one of the three alternatives.
- Preserve a tied group. Within ties, use candidate ID only for stable display order; do not prefer more diverse sequences. If the three-item limit cuts through a tie, disclose that equally ranked options were omitted from the short list.
- Missing or incomparable primary water evidence leaves that option unranked. Return only the supported ranked subset; if none is comparable, withhold the overall rank. Do not impute or replace missing values.
- Apply evidence-backed hard constraints before ranking. A review-needed calendar or crop suitability remains visible as a provisional warning; it does not become a fabricated pass or fail. Results are explicitly labelled provisional.
- Historical NASA POWER indicators remain attached for traceability, but do not adjust the crop-level class or predict future recommendation seasons.

This is a non-compensatory, lexicographic policy: soil cannot offset a worse water rating. Choosing an explicit criterion order is appropriate because the Product Owner has stated water comes first; incomplete multi-criteria methods also preserve incomparability rather than manufacture a complete score. See the methodology references below.

## 2. Water evidence table used by NY-8 v2

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

## 3. Soil-health tie-break policy

Ghana field research supports specific legume/fallow/residue relationships before maize under named treatments; it does not support a universal soil benefit for every legume or sequence. Soil-health effects depend on biomass, variety, residue fate, soil, and management. The current farm/result inputs do not capture enough of that context. Therefore:

1. Current NY-8 v2 emits soil-health potential as `not_assessed` for the public profile and does not use it to break a tie.
2. A later implementation may supply a sourced soil assessment only when sequence-specific evidence and required management inputs exist.
3. Soil may refine ordering only inside a tied water group and only if every option in that group has ratings on the same soil comparison basis. Otherwise leave the group tied.
4. Never describe a potential as measured soil health, nitrogen credit, or guaranteed yield improvement.

Relevant research includes [Ghana cowpea/legume–maize rotation work](https://doi.org/10.1017/S0014479718000273) and [maize rotations with food legumes on Ghanaian Vertisols](https://ugspace.ug.edu.gh/items/d346fb22-09de-4507-9c62-3d1c55e91c7e); results are treatment- and site-specific.

## 4. Ranking steps and response behavior

1. Generate three-event sequences deterministically. Keep the known current practice as a separate baseline. Repeated crops remain candidates and receive ROT-004 review warnings; do not add a blanket repeat or single-crop exclusion without an approved, evidence-backed rule.
2. Apply explicitly failed hard constraints before assessment. Keep `needs_review` constraints as visible warnings because the product has accepted provisional desk-research results; do not describe such results as validated.
3. Build the two active criterion records: water and soil. Each includes rating/status, confidence, rationale, comparison basis, citations, assumptions, and any historical NASA indicators. Require at least two usable approved NASA indicators in every past analysis period before assessing primary water; the underlying NY-13 policy permits two when one of three is unavailable and does not set a partial-coverage percentage threshold.
4. Partition by comparable water basis. If all assessed water evidence uses one basis, order High before Moderate before Low. Options missing water remain unranked. If rated options use different bases, withhold ranking rather than select a convenient majority basis.
5. Within a water tie only, order by soil if every tied option is assessed on one common basis. Missing soil is not a neutral rating and does not block water order.
6. Select no more than three alternatives. Within a tie, use candidate ID for stable display only; `tie_at_limit` and rationale disclose when the cutoff hides other equal alternatives. This ordering does not break the agronomic tie.
7. Return the baseline separately, plus candidate-pool counts, provisional status, crop-library/assessment/rule/scoring versions, per-option evidence, NASA snapshot references, and tie/withholding reasons.

The generator may examine 216 combinations from six crops internally. The API result's `scoring_result.options` contains no more than three alternatives; pool counts may appear as audit provenance. The returned list is not a prediction and does not imply that a displayed tied option is strictly better than another tied option. NY-13's existing minimum of two usable indicators in each past period is required before the primary water criterion can be assessed; partial indicators retain their coverage and no new coverage threshold is invented.

## 5. Why this handles the evidence blocker

Multi-criteria research distinguishes compensatory methods (one criterion can offset another) from non-compensatory/priority methods. A fixed lexicographic order makes water primary without inventing weights or allowing a soil estimate to compensate for weaker water evidence. Research on evidence-strength MCDA explicitly recognizes “incomparability” when evidence is not strong enough to distinguish options; incomplete-data decision methods preserve missingness or partial orders rather than silently inventing values. NovaYield uses the simplest auditable version of that idea: rank comparable water evidence, optionally refine a genuine tie, and otherwise keep the tie or withhold.

This reduces the evidence burden from three equally required comparisons to one primary comparison. It does **not** make weak evidence strong. Crop classes remain provisional, rice remains unranked until its ecology is known, soil is not currently used, and local validation is still required before describing results as agronomic advice.

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
