---
title: NY-9 pilot season-calendar evidence handoff
status: Provisional desk-research handoff; not a validated crop calendar or farm record
version: 0.1
prepared: 2026-11-03
---

# NY-9 Pilot Season-Calendar Evidence Handoff

## Purpose and status

This note separates three inputs that can otherwise be confused during NY-9 integration:

1. **A farmer's planting history** records what happened on that farmer's plot. It can support a current-practice baseline when the sequence and source are known.
2. **A crop/community calendar** describes sourced planting windows for a crop, place, and production system. The current Product Owner decision allows these windows to be shown as provisional when labelled with source and context.
3. **A NASA POWER date window** selects historical daily environmental observations. It does not prove that a farmer planted during that period or establish a crop calendar.

The findings below are desk research. They are not an agronomist-approved calendar, do not describe a particular farmer's history, and must remain provisional under Product Decision 9. Do not copy these periods into a farmer record or activate crop-dependent hard rules from them.

## Municipal season context

Published sources use different definitions and study periods for Ejura-Sekyedumase's seasons:

| Evidence | Reported context | How to use it |
| --- | --- | --- |
| Ghana MoFA district profile | Broadly describes the major season as April–August and minor season as August–November; reports rain-fed farming and erratic rainfall. | Useful as dated district-level background, not a current, crop-specific planting schedule. |
| Obour, Arthur & Owusu (2022), Ejura-Sekyedumase maize-failure study | Describes major rains from late March/early April to mid-July, a short dry spell into mid-August, and minor rains around September–October. The study used April–July and September–October as its major/minor climate-analysis periods. | Appropriate source for reproducing that study's historical weather-analysis windows. They remain analysis windows, not planting-event dates. |
| Obeng (2008), KNUST thesis using 1993–2006 precipitation data | Estimates 8 April and 31 August as suitable maize planting dates for major and minor seasons in that historical analysis. | Historical, maize-specific findings; not a current prescription. |

The municipality has both uni-modal and bi-modal rainfall patterns in different parts. A single municipality-wide calendar should therefore not silently be applied to every supported location, especially Kintampo, which is outside the Ejura-Sekyedumase pilot municipality. Calendar configuration should be keyed to the selected supported location and retain its source and validation status.

## Crop-by-crop evidence

| MVP crop | Evidence found | Safe calendar representation now | Limits and implementation consequence |
| --- | --- | --- | --- |
| **Maize** | The 2022 local study reports major-season planting in April with harvest in August, and minor-season planting from late August to early September with harvest in December. The KNUST analysis estimated 8 April and 31 August in its 1993–2006 record. | Provisional local planting-window statements: `major: April` and `minor: late August–early September`, each carrying its source and year/context. | The sources describe typical or historical practice and also report increasingly difficult rainfall onset. Do not turn them into guaranteed dates or crop-performance thresholds. |
| **Cowpea** | Codjoe (2004), an Ejura-Sekyedumase land-use study, says cowpea was planted in the minor rainy season. Hordzi's University of Cape Coast thesis (2008) cites Ghana-wide main-season sowing in April–July and minor-season planting in August–September. | A provisional season association may be recorded for research, but the exact Ejura community window is `unknown`. | The broader Ghana window is not specific enough to establish a local, crop/variety-specific calendar. Do not use it as a hard eligibility rule. |
| **Groundnut** | A 2020 on-farm Ejura maize–groundnut intercropping experiment planted maize on 21 April and 14 August; groundnut was introduced at the same time or one/two weeks after maize. | Record only as a study-specific intercropping observation, linked to the 2020 experiment. | This is not a general planting calendar for sole-crop groundnut or other varieties and farms. The current evidence does not establish a safe general window for the rotation engine. |
| **Cassava** | The 2004 local land-use study places cassava in the major rainy season; MoFA lists it among crops grown in the district. | Broad, provisional `major rainy season` association; exact planting dates remain `unknown`. | The source does not provide an exact crop/community planting window suitable for an API recommendation. |
| **Yam** | The 2004 study places yam in the major rainy season. A 2023 municipality study records an Anyinasu key informant's view that yam is normally planted in February–March, while reporting that many surveyed farmers change planting timing in response to climate variability. | Keep the reports as separate, dated evidence; do not select one universal window. | The sources reflect different years, methods, and farmer adaptation. A fixed window needs local extension/farmer validation and variety/system context. |
| **Rice** | An older Ejura-Sekyedumase survey records some rice cultivation. Ghana's rice strategy distinguishes rain-fed upland, rain-fed lowland, and irrigated systems. | Planting window and rice production system are `unknown` for a NovaYield farm unless the farm/system evidence is supplied. | A national rice calendar cannot identify the ecology of an individual farm or establish an Ejura-specific window. Do not model all rice as one system. |

Unknown here means no sufficiently scoped date range was found in the reviewed sources. It is not a recommendation to exclude that crop from the approved candidate library.

## Weather-analysis windows and planting events are separate

The existing NY-8 public profile contains example historical NASA analysis periods: April–July 2019, September–October 2019, and April–July 2020. These periods follow the 2022 study's definitions for comparing historical seasonal weather. They are suitable candidate **NASA query periods** for a reproducible research fixture, subject to retrieval and metadata validation.

They do not establish that a specific farm planted in those periods, document three consecutive planting events on one plot, or give crop-specific planting instructions. Do not pass them to NY-8 as validated `PlantingEventSlot`s merely because they have dates. If used as provisional slots after an explicit contract decision, preserve their status and source, ensure NY-8 returns `needs_review` where required, and withhold an overall rank when the approved evidence policy requires it.

The public profile has no known plot history. Its baseline must remain absent. For a real farm, a baseline can be included only when the farmer's three-event crop sequence and a traceable source are known; a free-text `current_practice` value such as “maize” does not supply that sequence.

## Recommended NY-9 behavior

- Keep the source, location scope, publication/study year, date window, and provisional/reviewed status with each calendar record.
- Resolve a supported `location_key` server-side. Do not expose the catalog coordinates in API responses or diagnostic logs.
- Keep calendar windows separate from NASA snapshot identity and from farmer-reported planting history. Use NY-6 for reusable NASA data and NY-7 for indicator calculation.
- Do not synthesize missing crop windows, farmer history, or three-event baselines. Preserve unknown fields and return client-safe `needs_review` or unavailable states.
- Do not label seasonal precipitation as farm water availability or interpret temperature as good/bad for a crop without an approved, sourced crop rule.
- Use historical NASA observations as environmental context. They are not future weather forecasts.
- Implement NY-9 subtask 1 (API composition and route mounting) independently of the missing crop calendar. Before a recommendation endpoint assembles NY-8 inputs, use only explicit, sourced, versioned calendar data; otherwise preserve the missing evidence and withhold a definitive rank.

## References

- Ejura-Sekyedumase Municipal Assembly / Ghana Ministry of Food and Agriculture, [Ejura-Sekyeredumase district profile](https://mofa.gov.gh/site/sports/district-directorates/ashanti-region/164-ejura-sekyeredumase): district crop and broad rainfall-season background; dated generalizations require caution.
- Obour, Arthur & Owusu (2022), [The 2020 Maize Production Failure in Ghana: A Case Study of Ejura-Sekyedumase Municipality](https://www.mdpi.com/2071-1050/14/6/3514), *Sustainability* 14(6), 3514: local maize planting/harvest periods, seasonal analysis windows, rainfall variability, and farmer observations.
- Obeng (2008), [KNUST thesis on rainfall, temperature, and maize in Ejura-Sekyedumase](https://ir.knust.edu.gh/handle/123456789/1050): historical precipitation-derived maize planting-date estimates for 1993–2006.
- Codjoe, S. N. A. (2004), [Population and Land Use/Cover Dynamics in the Volta River Basin of Ghana, 1960–2010](https://www.zef.de/fileadmin/webfiles/downloads/zefc_ecology_and_development/ecol_dev_15_text.pdf), Ecology and Development Series No. 15, section 6.1.2: field-survey crop/season associations in Ejura-Sekyedumase.
- Hordzi, W. H. K. (2008), [The Role of Insect Flower Visitors in Cowpea Agro-ecosystem in Three Districts in the Central Region of Ghana](https://ir.ucc.edu.gh/xmlui/bitstream/handle/123456789/8474/HORDZI%2C%202008.pdf?isAllowed=y&sequence=1), University of Cape Coast PhD thesis: cites Ghana-wide main/minor-season cowpea windows; it is not a local calendar for Ejura.
- Bugilla et al. (2023), [Effects of spatial row arrangement and time of planting intercrops on groundnut performance in Ejura](https://www.scirp.net/journal/paperinformation?paperid=123866): one 2020 local maize–groundnut intercropping experiment; not a universal sole-crop calendar.
- Baffour-Ata et al. (2023), [Determinants of yam farmers’ adaptation practices to climate variability in Ejura-Sekyedumase](https://pmc.ncbi.nlm.nih.gov/articles/PMC10008982/): 160 household surveys and key-informant evidence, including changing yam planting periods.
- Japan International Cooperation Agency / Ghana National Rice Development Strategy, [rice development strategy](https://www.jica.go.jp/english/our_work/thematic_issues/agricultural/pdf/ghana_en.pdf): distinguishes rain-fed upland, rain-fed lowland, and irrigated rice systems.
- Food and Agriculture Organization, [Ghana country crop calendar](https://cropcalendar.apps.fao.org/?isocode=GHA): national crop-calendar resource; location and crop-system detail still need checking before pilot use.
