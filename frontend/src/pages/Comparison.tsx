import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { farmApi, type EnvironmentalIndicator, type FarmResponse, type PriorityPoints } from '../api/farms';
import {
  recommendationApi,
  type ClimateFeature,
  type RotationResultResponse,
  type ScoredOption,
} from '../api/recommendations';
import DataSourceBadge from '../components/common/DataSourceBadge';
import IndicatorCard, { type IndicatorData } from '../components/indicators/IndicatorCard';

function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function featureValue(feature: ClimateFeature): string {
  if (feature.exposure_min_days === null || feature.exposure_max_days === null) return 'Not assessed';
  return `${feature.exposure_min_days}–${feature.exposure_max_days} ${feature.units}`;
}

function rankGroup(option: ScoredOption, result: RotationResultResponse): string {
  const groups = result.scoring_result.ranking?.rank_groups || [];
  const index = groups.findIndex((group) => group.includes(option.candidate.candidate_id));
  return index >= 0 ? `Rank group ${index + 1}` : 'Unranked';
}

function candidateLabel(candidateId: string, result: RotationResultResponse): string {
  const shown = result.scoring_result.options.find((option) => option.candidate.candidate_id === candidateId);
  return shown ? shown.candidate.events.map((item) => item.crop.display_name).join(' → ') : candidateId;
}

function collectIndicators(result: RotationResultResponse | null): EnvironmentalIndicator[] {
  if (!result) return [];
  const direct = result.indicators || [];
  const fromCriteria = result.scoring_result.options.flatMap((option) =>
    option.criteria.flatMap((criterion) => criterion.environmental_inputs || []),
  );
  return [...new Map([...direct, ...fromCriteria].map((indicator) => [
    `${indicator.code}:${indicator.period_start}:${indicator.period_end}`,
    indicator,
  ])).values()];
}

function toIndicatorData(indicator: EnvironmentalIndicator): IndicatorData {
  return {
    id: `${indicator.code}:${indicator.period_start}:${indicator.period_end}`,
    title: indicator.name,
    value: indicator.value,
    unit: indicator.units,
    description: indicator.definition,
    status: indicator.status,
    source: indicator.source || 'NASA POWER',
    dateRange: `${indicator.period_start} to ${indicator.period_end}`,
    calculationMethod: indicator.calculation_method,
    coverage: `${indicator.coverage.valid_days}/${indicator.coverage.expected_days} valid days (${indicator.coverage.coverage_percent}%)`,
  };
}

export default function Comparison() {
  const [searchParams] = useSearchParams();
  const farmId = searchParams.get('farmId');
  const [farm, setFarm] = useState<FarmResponse | null>(null);
  const [history, setHistory] = useState<RotationResultResponse[]>([]);
  const [result, setResult] = useState<RotationResultResponse | null>(null);
  const [loadedFarmId, setLoadedFarmId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [adjustPriorities, setAdjustPriorities] = useState(false);
  const [priorityPoints, setPriorityPoints] = useState<PriorityPoints>({
    water_resilience: 25,
    soil_health_potential: 25,
    yield_stability_proxy: 25,
    labor_feasibility: 25,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!farmId) return;
    let active = true;
    Promise.all([farmApi.getFarm(farmId), recommendationApi.listForFarm(farmId)])
      .then(([farmResponse, savedResults]) => {
        if (!active) return;
        setFarm(farmResponse);
        setError(null);
        const sorted = [...savedResults].sort((a, b) => b.created_at.localeCompare(a.created_at));
        setHistory(sorted);
        setResult(sorted[0] || null);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setFarm(null);
        setHistory([]);
        setResult(null);
        setError(cause instanceof Error ? cause.message : 'Could not load this plot.');
      })
      .finally(() => { if (active) setLoadedFarmId(farmId); });
    return () => { active = false; };
  }, [farmId]);

  const indicators = useMemo(() => collectIndicators(result).map(toIndicatorData), [result]);

  const generate = async () => {
    if (!farmId) return;
    if (adjustPriorities && Object.values(priorityPoints).some((points) => !Number.isInteger(points) || points < 0 || points > 100)) {
      setError('Each priority must be a whole number from 0 to 100.');
      return;
    }
    if (adjustPriorities && Object.values(priorityPoints).every((points) => points === 0)) {
      setError('At least one priority must have a point value above zero.');
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      // The saved Farm supplies all historical crops, dates, location, and
      // priorities. No farmer-entered NASA range or future slots are resent.
      const generated = await recommendationApi.generateForFarm(
        farmId,
        adjustPriorities ? priorityPoints : undefined,
      );
      setResult(generated);
      setHistory((items) => [generated, ...items.filter((item) => item.id !== generated.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save an assessment.');
    } finally {
      setGenerating(false);
    }
  };

  if (!farmId) {
    return <div className="page-container"><p className="alert alert-warning">Choose a saved plot first. <Link to="/field">Go to your plots</Link></p></div>;
  }
  if (loadedFarmId !== farmId) return <div className="page-container" role="status">Loading your saved plot and results…</div>;

  const storedIndicators = collectIndicators(result);
  // A historical result must be explained from its own saved provenance,
  // never from a farm context that may have changed after the result was saved.
  const contextPeriod = result ? result.derived_context_period : farm?.environmental_context?.period;
  const sourceStatus = result
    ? result.context_provenance?.data_status || storedIndicators[0]?.data_status || 'unknown'
    : farm?.environmental_context?.data_status || farm?.environmental_context?.status || 'unknown';
  const sourceProducts = result?.context_provenance?.source_products || [...new Set(storedIndicators.flatMap((item) => item.source_products || []))];
  const resolution = result?.context_provenance?.parameters.find((item) => item.spatial_resolution)?.spatial_resolution || storedIndicators.find((item) => item.spatial_resolution)?.spatial_resolution;
  const retrievedAt = result?.context_provenance?.retrieved_at || storedIndicators.find((item) => item.retrieved_at)?.retrieved_at;
  const isLegacy = result?.schema_version === 'ny20-result-v1';

  return (
    <div className="page-container comparison-page">
      <div className="comparison-header">
        <div>
          <Link to="/field">← Your plots</Link>
          <h1>{farm?.name || 'Plot assessment'}</h1>
          {farm && <p>{farm.location.label} · Saved history: {label(farm.history_status || 'unknown')}</p>}
        </div>
        <button type="button" className="submit-btn" disabled={generating || !farm || farm.history_status !== 'complete'} onClick={generate}>
          {generating ? 'Assessing saved plot…' : 'Assess saved plot'}
        </button>
      </div>

      {error && <p className="alert alert-error" role="alert">{error}</p>}
      {farm && farm.history_status !== 'complete' && (
        <p className="alert alert-warning">This plot has incomplete crop history. Review the missing dates, crop sequence, or gaps before requesting an assessment. A complete history still needs comparable crop and calendar evidence before an option can be ranked.</p>
      )}
      <p className="alert alert-warning">NASA POWER describes historical conditions at a regional grid point. It is not a future weather forecast, a field rain gauge, or a soil-moisture measurement. Crop and calendar evidence remains provisional pending local review.</p>

      {farm?.history_status === 'complete' && (
        <section className="priority-adjustment" aria-labelledby="priority-adjustment-heading">
          <h2 id="priority-adjustment-heading">Priorities for a new assessment</h2>
          <label className="checkbox-label"><input type="checkbox" checked={adjustPriorities} onChange={(event) => setAdjustPriorities(event.target.checked)} />Adjust the saved priorities for this assessment only</label>
          {adjustPriorities ? (
            <div className="priority-point-grid">
              {([
                ['water_resilience', 'Water resilience'],
                ['soil_health_potential', 'Soil health potential'],
                ['yield_stability_proxy', 'Yield stability proxy'],
                ['labor_feasibility', 'Labour feasibility'],
              ] as const).map(([key, title]) => (
                <div key={key} className="form-group">
                  <label htmlFor={`priority-${key}`}>{title} points</label>
                  <input id={`priority-${key}`} className="form-input" type="number" min={0} max={100} step={1} value={priorityPoints[key]} onChange={(event) => setPriorityPoints((current) => ({ ...current, [key]: Number(event.target.value) }))} />
                </div>
              ))}
            </div>
          ) : <p>The farm’s saved priorities are used. Adjusting points cannot override hard constraints or missing evidence.</p>}
        </section>
      )}

      {history.length > 0 && (
        <section className="result-history" aria-labelledby="history-results-heading">
          <h2 id="history-results-heading">Saved assessments</h2>
          <div className="result-history-list">
            {history.map((item) => (
              <button key={item.id} type="button" className={item.id === result?.id ? 'secondary-btn active-result' : 'secondary-btn'} onClick={() => setResult(item)}>
                {new Date(item.created_at).toLocaleString()} · {label(item.decision_status || item.scoring_result.ranking?.status || 'unknown')}
              </button>
            ))}
          </div>
        </section>
      )}

      {!result ? (
        <section className="empty-state">
          <h2>{farm?.history_status === 'complete' ? 'No assessment has been saved yet' : 'This plot needs review'}</h2>
          <p>{farm?.history_status === 'complete'
            ? 'Assess this plot’s saved history. NovaYield will reuse an eligible stored NASA snapshot and save the result for later review.'
            : 'Edit the saved plot to provide a complete, dated crop history before requesting a comparison.'}</p>
          {farm && farm.history_status !== 'complete' && <Link to="/field">Go to saved plots to edit</Link>}
        </section>
      ) : (
        <>
          <section className="result-overview" aria-labelledby="assessment-heading">
            <h2 id="assessment-heading">Assessment status</h2>
            <p><strong>{label(result.decision_status || result.scoring_result.ranking?.status || 'unknown')}</strong> · {result.scoring_result.provisional ? 'Provisional evidence' : 'Evidence status recorded'}</p>
            {isLegacy && <p className="alert alert-warning">This saved result uses the earlier request contract. Its historical crops and future windows were supplied differently; generate a new assessment to use the current saved-farm workflow.</p>}
            <p>Comparison mode: <strong>{result.scoring_result.ranking_mode ? label(result.scoring_result.ranking_mode) : 'Not available'}</strong>. Criteria used: {result.scoring_result.ranking?.criteria_used.map(label).join(', ') || 'none assessed on a comparable basis'}.</p>
            {result.scoring_result.selected_weights && (
              <p>Selected weights ({label(result.scoring_result.selected_weights.source)}): {result.scoring_result.selected_weights.normalized_weights.map((weight) => `${label(weight.criterion)} ${weight.percent}%`).join(' · ')}.</p>
            )}
            {result.future_window_summary && (
              <div className="schedule-status">
                <p>Future timing: {result.future_window_summary.fully_scheduled_count} of {result.future_window_summary.candidate_count} candidate sequences have three sourced planting and harvest windows. {result.future_window_summary.needs_review_count} need review.</p>
                {result.future_window_summary.review_reasons.length > 0 && <ul>{result.future_window_summary.review_reasons.map((reason, index) => <li key={index}>{label(reason)}</li>)}</ul>}
              </div>
            )}
            {result.scoring_result.ranking?.reasons.length ? <ul>{result.scoring_result.ranking.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : null}
          </section>

          {result.scoring_result.equal_weight_ranking && result.scoring_result.selected_weight_ranking && (
            <section className="result-overview" aria-labelledby="priority-comparison-heading">
              <h2 id="priority-comparison-heading">How priorities affect the order</h2>
              <p>Compare the same evidence under equal weights and the priorities used for this saved assessment. A rank group can contain tied options; only up to three options appear as cards below.</p>
              {result.scoring_result.sensitivity && <p>Priority sensitivity: {label(result.scoring_result.sensitivity)}.</p>}
              <div className="ranking-comparison-grid">
                {([
                  { title: 'Equal weights', ranking: result.scoring_result.equal_weight_ranking, weights: result.scoring_result.default_weights },
                  { title: 'Selected priorities', ranking: result.scoring_result.selected_weight_ranking, weights: result.scoring_result.selected_weights },
                ]).map((view) => (
                  <div className="ranking-comparison-card" key={view.title}>
                    <h3>{view.title}</h3>
                    <p>Status: {label(view.ranking.status)}.</p>
                    {view.weights && <p>Effective weights: {view.weights.normalized_weights.map((weight) => `${label(weight.criterion)} ${weight.percent}%`).join(' · ')}.</p>}
                    {view.ranking.rank_groups.length > 0 ? (
                      <ol>{view.ranking.rank_groups.map((group, index) => (
                        <li key={index}>Group {index + 1}: {group.map((id) => candidateLabel(id, result)).join(' · ')}</li>
                      ))}</ol>
                    ) : <p>No rank groups passed the evidence gate.</p>}
                  </div>
                ))}
              </div>
              <p>When an equal-weight option is outside the selected three-card shortlist, its stable candidate ID appears above so its order is still traceable.</p>
            </section>
          )}

          {result.history_event_snapshots?.length ? (
            <section className="result-overview" aria-labelledby="history-used-heading">
              <h2 id="history-used-heading">Crop history used for this saved result</h2>
              <ol>{result.history_event_snapshots.map((event) => (
                <li key={event.event_id}>{label(event.crop_key)} · {event.start_date || 'date unknown'} to {event.end_date || 'date unknown'}{event.variety_key ? ` · variety ${event.variety_key}` : ''}{event.production_system_key ? ` · system ${event.production_system_key}` : ''}</li>
              ))}</ol>
              <p>These are the inputs captured when this assessment was saved. Editing the plot later does not rewrite this result.</p>
            </section>
          ) : null}

          <section className="environmental-panel" aria-labelledby="environmental-heading">
            <h2 id="environmental-heading">Historical environmental context</h2>
            <DataSourceBadge
              status={sourceStatus}
              source={sourceProducts.length ? `NASA POWER · ${sourceProducts.join(', ')}` : 'NASA POWER'}
              dateRange={contextPeriod ? `${contextPeriod.start_date} to ${contextPeriod.end_date}` : 'Not available'}
              resolution={resolution}
              retrievedAt={retrievedAt}
            />
            {contextPeriod?.policy_version && <p>Period policy: {contextPeriod.policy_version}</p>}
            {result.context_provenance && (
              <p>Stored context: {label(result.context_provenance.cache_action)} · {label(result.context_provenance.freshness_status)} freshness · {result.context_provenance.start_date} to {result.context_provenance.end_date}.</p>
            )}
            {result.context_provenance?.parameters.map((parameter) => (
              <p key={parameter.code}>{parameter.code}: {parameter.valid_days}/{parameter.expected_days} valid days · {parameter.units}{parameter.source ? ` · ${parameter.source}` : ''}</p>
            ))}
            {result.context_provenance?.warning_codes.map((warning, index) => <p key={index} className="alert alert-warning">{label(warning)}</p>)}
            {result.climate_reference_provenance && (
              <p>Climate reference: {result.climate_reference_provenance.start_date} to {result.climate_reference_provenance.end_date} · {label(result.climate_reference_provenance.data_status)} · {label(result.climate_reference_provenance.freshness_status)}.</p>
            )}
            {result.environmental_snapshot_ids?.length ? (
              <details><summary>Stored NASA snapshot references</summary><ul>{result.environmental_snapshot_ids.map((id) => <li key={id}>{id}</li>)}</ul></details>
            ) : null}
            {result.climate_reference_provenance?.snapshot_id && (
              <details><summary>Climate reference snapshot</summary>{result.climate_reference_provenance.snapshot_id}</details>
            )}
            {indicators.length > 0 ? (
              <div className="indicators-grid">{indicators.map((indicator) => <IndicatorCard key={indicator.id} data={indicator} />)}</div>
            ) : <p>No complete indicator value is available in this saved assessment. Missing data was not treated as zero.</p>}
          </section>

          <section className="climate-features" aria-labelledby="feature-heading">
            <h2 id="feature-heading">NASA-derived decision evidence</h2>
            {result.climate_features?.length ? (
              <div className="feature-list">
                {result.climate_features.map((feature, index) => (
                  <article key={`${feature.feature_key}-${index}`} className="feature-card">
                    <h3>{label(feature.crop_id)} · {label(feature.stage_key)}</h3>
                    <p><strong>{featureValue(feature)}</strong> · {label(feature.status)}</p>
                    <p>Historical reference: {feature.reference_start_year}–{feature.reference_end_year} · {feature.source_products.join(', ') || 'source unavailable'}</p>
                    {feature.dry_day_definition && <p>Dry-day definition: {feature.dry_day_definition}. This is a meteorological measure, not a crop-damage threshold.</p>}
                    {feature.feasible_placement_count !== undefined && <p>{feature.feasible_placement_count} sourced crop-stage placements assessed; {feature.complete_years_per_placement || 0} complete reference years per placement.</p>}
                    <p>Evidence: {label(feature.evidence_status)} · Method: {feature.method_version}</p>
                    {feature.reason && <p>Review reason: {label(feature.reason)}</p>}
                    <p>{feature.interpretation}</p>
                  </article>
                ))}
              </div>
            ) : <p>There is no assessed numerical climate feature in this result. {result.climate_feature_status_reason ? `Review reason: ${label(result.climate_feature_status_reason)}. ` : ''}A NASA value is not assumed to affect ranking without a supported comparison rule.</p>}
          </section>

          <section aria-labelledby="options-heading">
            <h2 id="options-heading">Rotation alternatives</h2>
            {result.scoring_result.options.length === 0 && <p className="alert alert-warning">No alternative met the current evidence and comparison requirements. The result remains saved with reasons for review; no rank or planting date has been invented.</p>}
            <div className="rotation-options">
              {result.scoring_result.options.slice(0, 3).map((option) => (
                <article key={option.candidate.candidate_id} className="rotation-option">
                  <div className="option-heading">
                    <h3>{option.candidate.events.map((item) => item.crop.display_name).join(' → ')}</h3>
                    <span>{rankGroup(option, result)} · {label(option.candidate.readiness)}</span>
                  </div>
                  <h4>Three proposed crop events</h4>
                  <ol className="event-list">
                    {option.candidate.events.map(({ event, crop }, index) => (
                      <li key={`${option.candidate.candidate_id}-${index}`}>
                        <strong>{crop.display_name}</strong> · {event.window_start && event.window_end ? `Planting window ${event.window_start} to ${event.window_end}` : 'Planting window not established'}
                        {event.harvest_start && event.harvest_end && ` · Harvest or plot-release range ${event.harvest_start} to ${event.harvest_end}`}
                        <span> Calendar: {label(event.calendar_status || 'unknown')}{event.calendar_source ? ` · ${event.calendar_source}` : ''}</span>
                        {event.review_reasons?.map((reason, reasonIndex) => <p key={reasonIndex}>{reason}</p>)}
                      </li>
                    ))}
                  </ol>
                  <h4>Criteria assessed</h4>
                  <div className="criterion-grid">
                    {option.criteria.map((criterion) => (
                      <div key={criterion.criterion} className="criterion-card">
                        <strong>{label(criterion.criterion)}</strong>
                        <span>{criterion.status === 'assessed' && criterion.rating ? label(criterion.rating) : 'Not assessed'}</span>
                        {criterion.selected_weight_percent !== null && criterion.selected_weight_percent !== undefined && <small>Selected weight: {criterion.selected_weight_percent}%</small>}
                        <p>{criterion.rationale}</p>
                        {criterion.confidence && <small>Confidence: {label(criterion.confidence)}</small>}
                        {criterion.evidence_references.length > 0 && <small>Evidence: {criterion.evidence_references.join(', ')}</small>}
                      </div>
                    ))}
                  </div>
                  {option.benefits.length > 0 && <p><strong>Potential benefits:</strong> {option.benefits.join(' ')}</p>}
                  {option.trade_offs.length > 0 && <p><strong>Trade-offs:</strong> {option.trade_offs.join(' ')}</p>}
                  {option.assumptions.length > 0 && <p><strong>Assumptions:</strong> {option.assumptions.join(' ')}</p>}
                  {option.warnings.length > 0 && <p><strong>Review notes:</strong> {option.warnings.join(' ')}</p>}
                </article>
              ))}
            </div>
          </section>

          {result.scoring_result.options.length === 0 && !!result.unranked_calendar_examples?.length && (
            <section className="calendar-review-examples" aria-labelledby="calendar-examples-heading">
              <h2 id="calendar-examples-heading">Calendar examples for review — not recommendations</h2>
              <p className="alert alert-warning">These are unranked, complete dated sequences shown only to review the proposed calendar. They have no suitability finding, score, rank, benefit claim, or planting endorsement.</p>
              <div className="calendar-review-list">
                {result.unranked_calendar_examples.map((example) => (
                  <article className="calendar-review-example" key={example.candidate_id}>
                    <h3>{example.events.map((item) => item.crop.display_name).join(' → ')}</h3>
                    <p><strong>Review-only calendar example · {label(example.status)}</strong></p>
                    <ol className="event-list">
                      {example.events.map(({ event, crop }, index) => (
                        <li key={`${example.candidate_id}-${index}`}>
                          <strong>{crop.display_name}</strong> · {event.window_start && event.window_end ? `Planting window ${event.window_start} to ${event.window_end}` : 'Planting window missing; review required'}
                          {' · '}{event.harvest_start && event.harvest_end ? `Harvest or plot-release range ${event.harvest_start} to ${event.harvest_end}` : 'Harvest range missing; review required'}
                          <span> · Calendar evidence: {label(event.calendar_status || 'unknown')}{event.calendar_source ? ` · ${event.calendar_source}` : ''}</span>
                          {event.review_reasons?.map((reason, reasonIndex) => <p key={reasonIndex}>{reason}</p>)}
                        </li>
                      ))}
                    </ol>
                    {example.review_reasons.length > 0 && (
                      <div>
                        <h4>Why review is needed</h4>
                        <ul>{example.review_reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
                      </div>
                    )}
                    <p>{example.selection_note}</p>
                  </article>
                ))}
              </div>
            </section>
          )}

          {result.scoring_result.ranking?.tradeoffs.length ? (
            <section aria-labelledby="comparison-tradeoffs-heading">
              <h2 id="comparison-tradeoffs-heading">Why the order differs</h2>
              <ul>{result.scoring_result.ranking.tradeoffs.map((tradeoff, index) => <li key={index}>{tradeoff.explanation}</li>)}</ul>
            </section>
          ) : null}
          {result.scoring_result.ranking?.climate_tie_preferences?.length ? (
            <section aria-labelledby="climate-order-heading">
              <h2 id="climate-order-heading">How NASA evidence affected the order</h2>
              <p>Only a weighted-score tie among matching crop options can use the provisional dry-spell comparison. It does not add points to an unsupported criterion.</p>
              <ul>{result.scoring_result.ranking.climate_tie_preferences.map((preference, index) => <li key={index}>{preference.explanation} ({preference.policy_version})</li>)}</ul>
            </section>
          ) : null}
          <p className="result-version">Saved {new Date(result.created_at).toLocaleString()} · {result.schema_version} · {result.scoring_result.scoring_version}. {result.baseline_status === 'historical' ? 'This legacy result records a historical baseline; the current view does not display that older option.' : result.baseline_status === 'deferred' ? 'Current-practice baseline is deferred for this MVP.' : 'Baseline status was not recorded.'}</p>
        </>
      )}
    </div>
  );
}
