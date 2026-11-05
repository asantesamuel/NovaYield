import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  farmApi,
  type CropOption,
  type FarmEnvironmentalContext,
  type FarmCreateInput,
  type FarmReferenceOptionsResponse,
  type FarmResponse,
  type HistoryGapInput,
  type HistoryGapResponse,
  type PriorityPoints,
  type SupportedLocationsResponse,
} from '../api/farms';

type HistoryMode = 'complete' | 'needs_review' | 'unknown';
type GapStatus = HistoryGapInput['status'];
type PriorityKey = keyof PriorityPoints;

interface HistoryRow {
  id: number;
  cropKey: string;
  startDate: string;
  endDate: string;
  varietyKey: string | null;
  productionSystemKey: string | null;
}

const PRIORITIES: { key: PriorityKey; label: string }[] = [
  { key: 'water_resilience', label: 'Water resilience' },
  { key: 'soil_health_potential', label: 'Soil health potential' },
  { key: 'yield_stability_proxy', label: 'Yield stability proxy' },
  { key: 'labor_feasibility', label: 'Labour feasibility' },
];

const DEFAULT_PRIORITY_POINTS: PriorityPoints = {
  water_resilience: 25,
  soil_health_potential: 25,
  yield_stability_proxy: 25,
  labor_feasibility: 25,
};

function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

function nextDate(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}

function previousDate(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - 1);
  return value.toISOString().slice(0, 10);
}

function coversReportedGap(
  interval: { start: string; end: string },
  reports: HistoryGapResponse[],
): boolean {
  const within = reports
    .filter((report) => interval.start <= report.start_date && report.end_date <= interval.end)
    .sort((left, right) => left.start_date.localeCompare(right.start_date));
  return within.length > 0
    && within[0].start_date === interval.start
    && within[within.length - 1].end_date === interval.end
    && within.every((report, index) => report.status !== 'unknown'
      && (index === 0 || report.start_date === nextDate(within[index - 1].end_date)));
}

function gapLabel(status: GapStatus): string {
  return {
    fallow: 'Reported fallow',
    idle_unknown_management: 'Reported idle; management unknown',
    unknown: 'Farmer is unsure',
  }[status];
}

function contextLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: 'Ready',
    partial: 'Partial data',
    pending: 'Retrieving NASA data',
    unavailable: 'NASA data unavailable',
    needs_review: 'Needs history review',
    not_assessed: 'Not assessed',
  };
  return labels[status] || status.replaceAll('_', ' ');
}

export default function FieldSetup() {
  const nextRowId = useRef(2);
  const [locations, setLocations] = useState<SupportedLocationsResponse | null>(null);
  const [references, setReferences] = useState<FarmReferenceOptionsResponse | null>(null);
  const [crops, setCrops] = useState<CropOption[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [savedFarms, setSavedFarms] = useState<FarmResponse[]>([]);
  const [farmsError, setFarmsError] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [locationKey, setLocationKey] = useState('');
  const [soilKey, setSoilKey] = useState('');
  const [irrigationKey, setIrrigationKey] = useState('');
  const [historyMode, setHistoryMode] = useState<HistoryMode>('complete');
  const [historyRows, setHistoryRows] = useState<HistoryRow[]>([
    { id: 1, cropKey: '', startDate: '', endDate: '', varietyKey: null, productionSystemKey: null },
  ]);
  const [gapReports, setGapReports] = useState<HistoryGapResponse[]>([]);
  const [gapsTouched, setGapsTouched] = useState(false);
  const [historyClearConfirmed, setHistoryClearConfirmed] = useState(false);
  const [prioritiesEnabled, setPrioritiesEnabled] = useState(false);
  const [priorityPoints, setPriorityPoints] = useState<PriorityPoints>(DEFAULT_PRIORITY_POINTS);
  const [plotAvailable, setPlotAvailable] = useState<'yes' | 'no' | 'unknown'>('unknown');
  const [earliestAvailableDate, setEarliestAvailableDate] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [createdFarm, setCreatedFarm] = useState<FarmResponse | null>(null);
  const [editingFarm, setEditingFarm] = useState<FarmResponse | null>(null);
  const [historyTouched, setHistoryTouched] = useState(false);
  const [prioritiesTouched, setPrioritiesTouched] = useState(false);
  const [retryingFarmId, setRetryingFarmId] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([farmApi.listLocations(), farmApi.listReferences(), farmApi.listCrops()])
      .then(([locationResult, referenceResult, cropResult]) => {
        if (!active) return;
        setLocations(locationResult);
        setReferences(referenceResult);
        setCrops(cropResult.crops.filter((crop) => crop.history_selectable));
      })
      .catch((cause: unknown) => {
        if (active) setCatalogError(cause instanceof Error ? cause.message : 'Could not load farm choices.');
      })
      .finally(() => { if (active) setCatalogLoading(false); });
    farmApi.listFarms()
      .then((farms) => { if (active) setSavedFarms(farms); })
      .catch((cause: unknown) => {
        if (active) setFarmsError(cause instanceof Error ? cause.message : 'Could not load saved plots.');
      });
    return () => { active = false; };
  }, []);

  const updateRow = (id: number, change: Partial<HistoryRow>) => {
    setHistoryTouched(true);
    setHistoryClearConfirmed(false);
    // Existing gap reports remain visible after date edits. Validation asks
    // the farmer to explicitly remove or replace any interval that no longer fits.
    setHistoryRows((rows) => rows.map((row) => {
      if (row.id !== id) return row;
      const cropChanged = change.cropKey !== undefined && change.cropKey !== row.cropKey;
      return {
        ...row,
        ...change,
        varietyKey: cropChanged ? null : row.varietyKey,
        productionSystemKey: cropChanged ? null : row.productionSystemKey,
      };
    }));
  };

  const resetForm = () => {
    setCreatedFarm(null);
    setEditingFarm(null);
    setName('');
    setLocationKey('');
    setSoilKey('');
    setIrrigationKey('');
    setHistoryMode('complete');
    setHistoryRows([{ id: 1, cropKey: '', startDate: '', endDate: '', varietyKey: null, productionSystemKey: null }]);
    setGapReports([]);
    setGapsTouched(false);
    setHistoryClearConfirmed(false);
    setPrioritiesEnabled(false);
    setPriorityPoints(DEFAULT_PRIORITY_POINTS);
    setPlotAvailable('unknown');
    setEarliestAvailableDate('');
    setHistoryTouched(false);
    setPrioritiesTouched(false);
    setSubmitError(null);
    setRetryError(null);
    nextRowId.current = 2;
  };

  const beginEdit = (farm: FarmResponse) => {
    const rows = farm.crop_history?.length
      ? farm.crop_history.map((item, index) => ({
        id: index + 1,
        cropKey: item.crop?.key || '',
        startDate: item.start_date || '',
        endDate: item.end_date || '',
        varietyKey: item.variety_key || null,
        productionSystemKey: item.production_system_key || null,
      }))
      : [{ id: 1, cropKey: '', startDate: '', endDate: '', varietyKey: null, productionSystemKey: null }];
    setEditingFarm(farm);
    setCreatedFarm(null);
    setName(farm.name);
    setLocationKey(farm.location.location_key || farm.location.key || '');
    setSoilKey(farm.soil_texture?.key || '');
    setIrrigationKey(farm.irrigation_access?.key || '');
    setHistoryMode(farm.history_status === 'legacy_unresolved' ? 'needs_review' : (farm.history_status as HistoryMode || 'needs_review'));
    setHistoryRows(rows);
    setGapReports(farm.declared_gaps || []);
    setGapsTouched(false);
    setHistoryClearConfirmed(false);
    setPrioritiesEnabled(farm.farmer_priorities !== null && farm.farmer_priorities !== undefined);
    setPriorityPoints(farm.farmer_priorities || DEFAULT_PRIORITY_POINTS);
    setPlotAvailable(farm.current_plot_available === null || farm.current_plot_available === undefined ? 'unknown' : farm.current_plot_available ? 'yes' : 'no');
    setEarliestAvailableDate(farm.earliest_available_date || '');
    setHistoryTouched(false);
    setPrioritiesTouched(false);
    setSubmitError(null);
    setRetryError(null);
    nextRowId.current = rows.length + 1;
  };

  const gaps = historyRows.slice(1).flatMap((row, index) => {
    const before = historyRows[index];
    if (!before.endDate || !row.startDate || nextDate(before.endDate) >= row.startDate) return [];
    return [{ key: `${before.id}-${row.id}`, start: nextDate(before.endDate), end: previousDate(row.startDate) }];
  });
  const hasEnteredHistory = historyRows.some((row) => row.cropKey || row.startDate || row.endDate)
    || gapReports.length > 0;

  const validate = (): string | null => {
    if (!name.trim() || !locationKey || !soilKey || !irrigationKey) {
      return 'Enter a plot name and select a supported location, soil texture, and irrigation option.';
    }
    if (plotAvailable === 'yes' && !earliestAvailableDate) {
      return 'Give the earliest date when this free plot could be planted.';
    }
    const lastReportedEnd = historyRows.map((row) => row.endDate).filter(Boolean).sort().at(-1);
    if (earliestAvailableDate && lastReportedEnd && earliestAvailableDate < lastReportedEnd) {
      return 'The plot cannot become available before the last reported crop ended.';
    }
    if (prioritiesEnabled) {
      const points = Object.values(priorityPoints);
      if (points.some((point) => !Number.isInteger(point) || point < 0 || point > 100)) {
        return 'Each priority must be a whole number from 0 to 100.';
      }
      if (points.every((point) => point === 0)) {
        return 'At least one priority must have a point value above zero.';
      }
    }
    if (historyMode === 'unknown') {
      if (hasEnteredHistory && !historyClearConfirmed) {
        return 'Clear the recorded crop history and gap reports explicitly before saving an unknown history.';
      }
      return null;
    }
    const reported = historyRows.filter((row) => row.cropKey || row.startDate || row.endDate);
    if (historyMode === 'complete' && reported.length !== historyRows.length) {
      return 'Complete every crop event, or save a report that needs review.';
    }
    for (const row of reported) {
      if (!row.cropKey) return 'Select a catalog crop for each reported event.';
      if (historyMode === 'complete' && (!row.startDate || !row.endDate)) {
        return 'Enter the actual start and end dates for every crop, or save for review.';
      }
      if (row.startDate && row.endDate && row.endDate < row.startDate) {
        return 'A crop end date cannot be before its start date.';
      }
      if ((row.startDate && row.startDate > todayUtc()) || (row.endDate && row.endDate > todayUtc())) {
        return 'Previous crop dates cannot be in the future.';
      }
    }
    for (let index = 1; index < reported.length; index += 1) {
      if (reported[index].startDate && reported[index - 1].startDate && (
        reported[index].startDate < reported[index - 1].startDate
        || (historyMode === 'complete' && reported[index].startDate === reported[index - 1].startDate)
      )) {
        return 'Crop event planting dates must agree with the oldest-first order.';
      }
    }
    const orderedReports = [...gapReports].sort((left, right) => left.start_date.localeCompare(right.start_date));
    if (orderedReports.some((report, index) => index > 0 && report.start_date <= orderedReports[index - 1].end_date)) {
      return 'Reported gaps cannot overlap. Remove or replace a conflicting report.';
    }
    if (gapReports.some((report) => !gaps.some((gap) => gap.start <= report.start_date && report.end_date <= gap.end))) {
      return 'A saved gap no longer fits the crop dates. Remove that report explicitly or restore the crop dates.';
    }
    if (gapsTouched && gapReports.some((report) => report.source === 'extension_verified')) {
      return 'An extension-verified gap needs reviewer support before its reports can be changed.';
    }
    if (historyMode === 'complete') {
      for (let index = 1; index < reported.length; index += 1) {
        if (reported[index].startDate <= reported[index - 1].endDate) {
          return 'Previous crops must be ordered oldest first and cannot overlap on this plot.';
        }
      }
      if (gaps.some((gap) => !coversReportedGap(gap, gapReports))) {
        return 'Confirm what happened between the reported crops, or save for review.';
      }
    }
    return null;
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitError(null);
    const validationError = validate();
    if (validationError) {
      setSubmitError(validationError);
      return;
    }

    const reported = historyMode === 'unknown'
      ? []
      : historyRows.filter((row) => row.cropKey || row.startDate || row.endDate);
    const selectedPriorities = prioritiesEnabled ? priorityPoints : prioritiesTouched ? null : undefined;
    const declaredGaps: HistoryGapInput[] = historyMode === 'unknown'
      ? []
      : gapReports.map((gap) => ({
          start_date: gap.start_date,
          end_date: gap.end_date,
          status: gap.status,
          source: 'farmer_reported',
        }));

    setSubmitting(true);
    try {
      const payload: FarmCreateInput = {
        name: name.trim(),
        location_key: locationKey,
        soil_texture_key: soilKey,
        irrigation_access_key: irrigationKey,
        history_status: historyMode,
        crop_history: reported.map((row, index) => ({
          crop_key: row.cropKey,
          sequence_order: index + 1,
          start_date: row.startDate || null,
          end_date: row.endDate || null,
          variety_key: row.varietyKey,
          production_system_key: row.productionSystemKey,
        })),
        declared_gaps: declaredGaps,
        farmer_priorities: selectedPriorities,
        current_plot_available: plotAvailable === 'unknown' ? null : plotAvailable === 'yes',
        earliest_available_date: plotAvailable === 'unknown' ? null : earliestAvailableDate || null,
      };
      let farm: FarmResponse;
      if (editingFarm) {
        const patch: Partial<FarmCreateInput> = {};
        if (payload.name !== editingFarm.name) patch.name = payload.name;
        if (payload.location_key !== (editingFarm.location.location_key || editingFarm.location.key)) patch.location_key = payload.location_key;
        if (payload.soil_texture_key !== editingFarm.soil_texture?.key) patch.soil_texture_key = payload.soil_texture_key;
        if (payload.irrigation_access_key !== editingFarm.irrigation_access?.key) patch.irrigation_access_key = payload.irrigation_access_key;
        if (historyTouched || editingFarm.history_status === 'legacy_unresolved') {
          patch.history_status = payload.history_status;
          patch.crop_history = payload.crop_history;
        }
        if (gapsTouched || historyClearConfirmed || editingFarm.history_status === 'legacy_unresolved') {
          patch.declared_gaps = declaredGaps;
        }
        if (prioritiesTouched) patch.farmer_priorities = selectedPriorities;
        if (payload.current_plot_available !== (editingFarm.current_plot_available ?? null)) {
          patch.current_plot_available = payload.current_plot_available;
        }
        if (payload.earliest_available_date !== (editingFarm.earliest_available_date ?? null)) {
          patch.earliest_available_date = payload.earliest_available_date;
        }
        if (Object.keys(patch).length === 0) {
          setSubmitError('No changes to save.');
          return;
        }
        farm = await farmApi.updateFarm(editingFarm.id, patch);
      } else {
        farm = await farmApi.createFarm(payload);
      }
      setCreatedFarm(farm);
      setEditingFarm(null);
      setRetryError(null);
      setSavedFarms((farms) => [farm, ...farms.filter((item) => item.id !== farm.id)]);
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : 'Could not save this plot.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetry = async (farmId: string) => {
    setRetryingFarmId(farmId);
    setRetryError(null);
    try {
      const result = await farmApi.retryEnvironmentalContext(farmId);
      const retriedContext: FarmEnvironmentalContext = {
        status: result.context_status,
        period: result.period || null,
        data_status: result.data_status as FarmEnvironmentalContext['data_status'],
        snapshot_id: result.snapshot_id,
        cache_action: result.cache_action,
        warning_code: result.error_code,
      };
      setCreatedFarm((current) => current?.id === farmId ? { ...current, environmental_context: retriedContext } : current);
      setSavedFarms((farms) => farms.map((farm) => farm.id === farmId ? { ...farm, environmental_context: retriedContext } : farm));
    } catch (cause) {
      setRetryError(cause instanceof Error ? cause.message : 'Could not retry NASA retrieval.');
    } finally {
      setRetryingFarmId(null);
    }
  };

  const context = createdFarm?.environmental_context;

  return (
    <div className="page-container">
      <section className="form-card" aria-labelledby="setup-heading">
        <div className="form-header">
          <h1 id="setup-heading">{editingFarm ? `Edit ${editingFarm.name}` : 'Set up a plot'}</h1>
          <p>Report the crops grown on one plot. NovaYield saves your account-owned profile and retrieves historical NASA POWER context for the supported location.</p>
        </div>

        {farmsError && <p className="alert alert-error" role="alert">{farmsError}</p>}
        {retryError && <p className="alert alert-error" role="alert">{retryError}</p>}
        {savedFarms.length > 0 && (
          <section className="saved-farms" aria-labelledby="saved-farms-heading">
            <h2 id="saved-farms-heading">Your saved plots</h2>
            <ul>
              {savedFarms.map((farm) => (
                <li key={farm.id}>
                  <span>{farm.name} · {farm.location.label} · {contextLabel(farm.environmental_context?.status || farm.history_status || 'pending')}</span>
                  <span className="saved-farm-actions">
                    <button type="button" className="text-btn" onClick={() => beginEdit(farm)}>Edit details</button>
                    {farm.history_status === 'complete' && farm.environmental_context?.status !== 'ready' && (
                      <button type="button" className="text-btn" disabled={retryingFarmId !== null} onClick={() => handleRetry(farm.id)}>
                        {retryingFarmId === farm.id ? 'Refreshing NASA context…' : 'Refresh NASA context'}
                      </button>
                    )}
                    <Link to={`/comparison?farmId=${encodeURIComponent(farm.id)}`}>{farm.history_status === 'complete' ? 'View assessment' : 'View review status'}</Link>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {createdFarm ? (
          <section className="saved-confirmation" aria-live="polite">
            <h2>{createdFarm.name} is saved</h2>
            <p>{createdFarm.location.label}. {createdFarm.crop_history?.some((item) => item.start_date || item.end_date) ? 'Your reported crop dates remain exactly as entered.' : 'No crop dates were inferred for this report.'}</p>
            <p><strong>Environmental context:</strong> {contextLabel(context?.status || 'pending')}</p>
            {context?.data_status && context.data_status !== 'unavailable' && <p>NASA source: {context.data_status === 'cached' ? 'Reused a stored snapshot' : 'Retrieved from NASA POWER'}.</p>}
            {context?.period && (
              <p>Derived historical period: <strong>{context.period.start_date} to {context.period.end_date}</strong>. NovaYield chose this range from the saved history; it is not a forecast.</p>
            )}
            {context?.warning_code && <p className="alert alert-warning">Retrieval note: {context.warning_code}</p>}
            <div className="action-row">
              {createdFarm.history_status === 'complete' && context?.status !== 'ready' && (
                <button type="button" className="secondary-btn" disabled={retryingFarmId !== null} onClick={() => handleRetry(createdFarm.id)}>
                  {retryingFarmId === createdFarm.id ? 'Refreshing NASA context…' : 'Refresh NASA context'}
                </button>
              )}
              <Link className="submit-btn" to={`/comparison?farmId=${encodeURIComponent(createdFarm.id)}`}>{createdFarm.history_status === 'complete' ? 'View assessment' : 'View review status'}</Link>
              <button type="button" className="secondary-btn" onClick={resetForm}>Set up another plot</button>
            </div>
          </section>
        ) : (
          <>
            {catalogLoading && <p role="status">Loading supported locations and crop choices…</p>}
            {catalogError && <p className="alert alert-error" role="alert">{catalogError} Reload this page to retry.</p>}
            {!catalogLoading && !catalogError && locations && references && (
              <form onSubmit={handleSubmit} className="form-grid">
                {editingFarm?.history_status === 'legacy_unresolved' && (
                  <div className="alert alert-warning form-span">
                    <p>This older profile has text entries without reliable dates or catalog references. They were not converted automatically. Select the current catalog options and report only crop history you actually know.</p>
                    {editingFarm.legacy_unresolved_inputs?.previous_crops?.length ? <p>Previous crop text: {editingFarm.legacy_unresolved_inputs.previous_crops.join(', ')}.</p> : null}
                    {editingFarm.legacy_unresolved_inputs?.soil_texture && <p>Previous soil text: {editingFarm.legacy_unresolved_inputs.soil_texture}.</p>}
                    {editingFarm.legacy_unresolved_inputs?.irrigation_access && <p>Previous irrigation text: {editingFarm.legacy_unresolved_inputs.irrigation_access}.</p>}
                  </div>
                )}
                <p className="alert alert-warning form-span">{locations.coverage_notice} The place names are reference locations, not coordinates measured on your plot.</p>
                <div className="form-group">
                  <label htmlFor="plot-name">Plot name</label>
                  <input id="plot-name" className="form-input" required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="For example, North plot" />
                </div>
                <div className="form-group">
                  <label htmlFor="location">Supported location</label>
                  <select id="location" className="form-select" required value={locationKey} onChange={(event) => setLocationKey(event.target.value)}>
                    <option value="">Choose a location</option>
                    {locations.locations.map((location) => <option key={location.location_key} value={location.location_key}>{location.label}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label htmlFor="soil">Soil texture</label>
                  <select id="soil" className="form-select" required value={soilKey} onChange={(event) => setSoilKey(event.target.value)}>
                    <option value="">Choose an option</option>
                    {references.soil_textures.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
                  </select>
                  {soilKey && <small>{references.soil_textures.find((option) => option.key === soilKey)?.definition}</small>}
                  <small>Choose “I do not know” if unsure. A texture choice does not measure soil water storage.</small>
                </div>
                <div className="form-group">
                  <label htmlFor="irrigation">Irrigation access</label>
                  <select id="irrigation" className="form-select" required value={irrigationKey} onChange={(event) => setIrrigationKey(event.target.value)}>
                    <option value="">Choose an option</option>
                    {references.irrigation_access.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
                  </select>
                  {irrigationKey && <small>{references.irrigation_access.find((option) => option.key === irrigationKey)?.definition}</small>}
                  <small>Access does not tell us how much water reaches a crop.</small>
                </div>

                <section className="form-span form-section" aria-labelledby="history-heading">
                  <h2 id="history-heading">Previous crops on this plot</h2>
                  <p>Enter one to three events in the order they happened, oldest first. Dates are the actual planting and removal or harvest dates. Unknown details can be saved for review.</p>
                  <div className="form-group">
                    <label htmlFor="history-mode">How complete is this history?</label>
                    <select id="history-mode" className="form-select" value={historyMode} onChange={(event) => { setHistoryTouched(true); setHistoryClearConfirmed(false); setHistoryMode(event.target.value as HistoryMode); }}>
                      <option value="complete">I can report exact dates and order</option>
                      <option value="needs_review">Some dates, gaps, or crops need review</option>
                      <option value="unknown">I cannot report previous crops yet</option>
                    </select>
                  </div>
                  {historyMode === 'unknown' && hasEnteredHistory && (
                    <div className="form-group">
                      <p>Choosing unknown removes the crop events and gap reports already entered for this plot.</p>
                      <button type="button" className="secondary-btn" onClick={() => {
                        setHistoryRows([{ id: 1, cropKey: '', startDate: '', endDate: '', varietyKey: null, productionSystemKey: null }]);
                        setGapReports([]);
                        setHistoryTouched(true);
                        setGapsTouched(true);
                        setHistoryClearConfirmed(true);
                      }}>Clear recorded crop history and gap reports</button>
                    </div>
                  )}
                  {historyMode !== 'unknown' && (
                    <>
                      {historyRows.map((row, index) => (
                        <div key={row.id} className="history-row">
                          <div className="history-row-heading">
                            <h3>Crop event {index + 1}</h3>
                            {historyRows.length > 1 && <button type="button" className="text-btn" onClick={() => { setHistoryTouched(true); setHistoryClearConfirmed(false); setHistoryRows((rows) => rows.filter((item) => item.id !== row.id)); }}>Remove</button>}
                          </div>
                          <div className="history-row-grid">
                            <div className="form-group">
                              <label htmlFor={`crop-${row.id}`}>Crop</label>
                              <select id={`crop-${row.id}`} className="form-select" value={row.cropKey} onChange={(event) => updateRow(row.id, { cropKey: event.target.value })}>
                                <option value="">Choose a crop</option>
                                {crops.map((crop) => <option key={crop.id} value={crop.crop_key}>{crop.common_name}</option>)}
                              </select>
                              {crops.find((crop) => crop.crop_key === row.cropKey)?.requires_variety_for_timing && <small>Future timing for this crop needs a sourced variety record. Choosing a crop here does not establish that record.</small>}
                              {crops.find((crop) => crop.crop_key === row.cropKey)?.requires_production_system_for_assessment && <small>A sourced production system is needed for crop-specific assessment. It is not inferred from irrigation access.</small>}
                            </div>
                            <div className="form-group">
                              <label htmlFor={`start-${row.id}`}>Planting date</label>
                              <input id={`start-${row.id}`} className="form-input" type="date" max={todayUtc()} value={row.startDate} onChange={(event) => updateRow(row.id, { startDate: event.target.value })} />
                            </div>
                            <div className="form-group">
                              <label htmlFor={`end-${row.id}`}>Harvest or removal date</label>
                              <input id={`end-${row.id}`} className="form-input" type="date" max={todayUtc()} value={row.endDate} onChange={(event) => updateRow(row.id, { endDate: event.target.value })} />
                            </div>
                          </div>
                        </div>
                      ))}
                      {historyRows.length < 3 && <button type="button" className="secondary-btn" onClick={() => { setHistoryTouched(true); setHistoryClearConfirmed(false); setHistoryRows((rows) => [...rows, { id: nextRowId.current++, cropKey: '', startDate: '', endDate: '', varietyKey: null, productionSystemKey: null }]); }}>Add another crop event</button>}
                      {gapReports.length > 0 && (
                        <div className="form-group gap-choice">
                          <h3>Saved gap reports</h3>
                          <p>These reports remain saved when you edit other details. If crop dates change, remove a report explicitly before saving if it no longer fits.</p>
                          <ul>
                            {gapReports.map((report) => (
                              <li key={`${report.start_date}-${report.end_date}`}>
                                {report.start_date} to {report.end_date}: {gapLabel(report.status)}{report.source === 'extension_verified' ? ' (extension verified)' : ''}
                                {report.source === 'farmer_reported' && <button type="button" className="text-btn" onClick={() => { setGapsTouched(true); setGapReports((current) => current.filter((item) => item !== report)); }}>Remove report</button>}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {gaps.map((gap) => (
                        <div className="form-group gap-choice" key={gap.key}>
                          <label htmlFor={`gap-${gap.key}`}>What happened on this plot from {gap.start} to {gap.end}?</label>
                          <select id={`gap-${gap.key}`} className="form-select" disabled={gapReports.some((report) => report.source === 'extension_verified' && gap.start <= report.start_date && report.end_date <= gap.end)} value={gapReports.find((report) => report.start_date === gap.start && report.end_date === gap.end)?.status || ''} onChange={(event) => {
                            const selected = event.target.value as GapStatus | '';
                            setGapsTouched(true);
                            setGapReports((current) => {
                              const outside = current.filter((report) => report.end_date < gap.start || report.start_date > gap.end);
                              return selected ? [...outside, { start_date: gap.start, end_date: gap.end, status: selected, source: 'farmer_reported' }] : outside;
                            });
                          }}>
                            <option value="">No full-interval report</option>
                            <option value="fallow">I left this plot fallow</option>
                            <option value="idle_unknown_management">It was idle; management is unknown</option>
                            <option value="unknown">I am unsure what happened</option>
                          </select>
                          <small>Changing this choice replaces farmer reports within this interval. Extension-verified reports need reviewer support before a change. An unconfirmed or unknown interval needs review; NovaYield does not assume it was fallow.</small>
                        </div>
                      ))}
                    </>
                  )}
                </section>

                <section className="form-span form-section" aria-labelledby="availability-heading">
                  <h2 id="availability-heading">Plot availability</h2>
                  <p>Past harvest dates do not prove the plot is free for the next planting.</p>
                  <div className="form-group">
                    <label htmlFor="plot-available">Is this plot currently available for a new crop?</label>
                    <select id="plot-available" className="form-select" value={plotAvailable} onChange={(event) => setPlotAvailable(event.target.value as 'yes' | 'no' | 'unknown')}>
                      <option value="unknown">I do not know</option>
                      <option value="yes">Yes, it is free</option>
                      <option value="no">No, it is occupied</option>
                    </select>
                  </div>
                  {plotAvailable !== 'unknown' && (
                    <div className="form-group">
                      <label htmlFor="earliest-date">Earliest known date this plot can be planted {plotAvailable === 'no' ? '(if known)' : ''}</label>
                      <input id="earliest-date" className="form-input" type="date" required={plotAvailable === 'yes'} value={earliestAvailableDate} onChange={(event) => setEarliestAvailableDate(event.target.value)} />
                    </div>
                  )}
                </section>

                <section className="priorities-section" aria-labelledby="priorities-heading">
                  <h2 id="priorities-heading">Farmer priorities</h2>
                  <p>Use default balanced weights or set your own points. The backend normalizes points across criteria with comparable evidence. Priorities cannot override hard constraints or missing evidence.</p>
                  <label className="checkbox-label">
                    <input type="checkbox" checked={prioritiesEnabled} onChange={(event) => { setPrioritiesTouched(true); setPrioritiesEnabled(event.target.checked); }} />
                    Set my own priority points
                  </label>
                  {prioritiesEnabled && (
                    <div className="priority-point-grid">
                      {PRIORITIES.map(({ key, label: priorityLabel }) => (
                        <div key={key} className="form-group">
                          <label htmlFor={`farm-priority-${key}`}>{priorityLabel} points</label>
                          <input id={`farm-priority-${key}`} className="form-input" type="number" min={0} max={100} step={1} value={priorityPoints[key]} onChange={(event) => { setPrioritiesTouched(true); setPriorityPoints((current) => ({ ...current, [key]: Number(event.target.value) })); }} />
                        </div>
                      ))}
                    </div>
                  )}
                  {prioritiesEnabled && <small>Each point value must be 0–100, with at least one above zero. Saved values are kept exactly when you edit another plot detail.</small>}
                </section>

                {historyMode !== 'complete' && <p className="alert alert-warning form-span">This profile can be saved, but incomplete history cannot support a ranked sequence or NASA context until it is reviewed.</p>}
                {submitError && <p className="alert alert-error form-span" role="alert">{submitError}</p>}
                <div className="form-actions">
                  <button type="submit" disabled={submitting} className="submit-btn">
                    {submitting ? 'Saving and checking environmental context…' : editingFarm ? 'Save plot changes' : 'Save plot'}
                  </button>
                  {editingFarm && <button type="button" className="secondary-btn" onClick={resetForm}>Cancel edit</button>}
                </div>
              </form>
            )}
          </>
        )}
      </section>
    </div>
  );
}
