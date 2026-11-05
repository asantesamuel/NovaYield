import { api } from './client';

export interface CropOption {
  id: string;
  crop_key: string;
  common_name: string;
  scientific_name?: string | null;
  history_selectable: boolean;
  recommendation_candidate: boolean;
  evidence_status: string;
  requires_variety_for_timing?: boolean;
  requires_production_system_for_assessment?: boolean;
}

export interface CropCatalogResponse {
  catalog_version: string;
  crops: CropOption[];
}

export interface ReferenceOption {
  key: string;
  label: string;
  definition: string;
}

export interface FarmReferenceOptionsResponse {
  catalog_version: string;
  soil_textures: ReferenceOption[];
  irrigation_access: ReferenceOption[];
}

export interface SupportedLocationsResponse {
  coverage_notice: string;
  locations: { location_key: string; label: string }[];
}

export interface PriorityPoints {
  water_resilience: number;
  soil_health_potential: number;
  yield_stability_proxy: number;
  labor_feasibility: number;
}

export interface CropHistoryInput {
  crop_key: string;
  sequence_order: number;
  start_date: string | null;
  end_date: string | null;
  variety_key?: string | null;
  production_system_key?: string | null;
}

export interface HistoryGapInput {
  start_date: string;
  end_date: string;
  status: 'fallow' | 'idle_unknown_management' | 'unknown';
  source: 'farmer_reported';
}

export interface HistoryGapResponse extends Omit<HistoryGapInput, 'source'> {
  source: 'farmer_reported' | 'extension_verified';
}

export interface FarmCreateInput {
  name: string;
  location_key: string;
  soil_texture_key: string;
  irrigation_access_key: string;
  history_status: 'complete' | 'needs_review' | 'unknown';
  crop_history: CropHistoryInput[];
  declared_gaps?: HistoryGapInput[];
  farmer_priorities?: PriorityPoints | null;
  current_plot_available?: boolean | null;
  earliest_available_date?: string | null;
}

export interface ContextPeriod {
  start_date: string;
  end_date: string;
  policy_version?: string;
  history_start?: string;
  history_end?: string;
}

export interface FarmEnvironmentalContext {
  status: 'pending' | 'ready' | 'partial' | 'unavailable' | 'not_assessed' | 'needs_review';
  period: ContextPeriod | null;
  snapshot_id?: string | null;
  data_status?: 'live' | 'cached' | 'unavailable' | null;
  cache_action?: string | null;
  warning_code?: string | null;
}

export interface FarmResponse {
  id: string;
  revision?: number;
  name: string;
  location: { location_key?: string; key?: string; label: string };
  soil_texture?: { key: string; label: string } | null;
  irrigation_access?: { key: string; label: string } | null;
  history_status?: string;
  farmer_priorities?: PriorityPoints | null;
  crop_history?: {
    event_id: string;
    crop?: { key: string; label: string };
    sequence_order: number;
    start_date: string | null;
    end_date: string | null;
    variety_key?: string | null;
    production_system_key?: string | null;
  }[];
  declared_gaps?: HistoryGapResponse[];
  current_plot_available?: boolean | null;
  earliest_available_date?: string | null;
  legacy_unresolved_inputs?: {
    previous_crops: string[] | null;
    soil_texture: string | null;
    irrigation_access: string | null;
  } | null;
  environmental_context?: FarmEnvironmentalContext | null;
}

export interface EnvironmentalIndicator {
  code: string;
  name: string;
  definition: string;
  calculation_method: string;
  value: number | null;
  units: string;
  status: string;
  data_status: string;
  source: string | null;
  source_products: string[];
  period_start: string;
  period_end: string;
  retrieved_at: string | null;
  coverage: {
    expected_days: number;
    valid_days: number;
    missing_days: number;
    coverage_percent: number;
  };
  spatial_resolution: string | null;
  warnings: string[];
}

export interface EnvironmentalContextResponse {
  farm_id: string;
  snapshot_id?: string | null;
  farm_revision?: number;
  derived_period?: ContextPeriod;
  period?: ContextPeriod;
  data_status: string;
  context_status: FarmEnvironmentalContext['status'];
  cache_action?: string;
  freshness_status?: string;
  freshness_explanation?: string;
  error_code?: string | null;
  indicators: EnvironmentalIndicator[];
  warnings: string[];
  sources?: {
    snapshot_id: string;
    source: string;
    period: ContextPeriod;
    retrieved_at: string;
    status: string;
    coverage?: unknown;
    documented_source_grid?: string | null;
  }[];
}

export const farmApi = {
  listLocations: () => api.get<SupportedLocationsResponse>('/farms/locations'),
  listCrops: () => api.get<CropCatalogResponse>('/crops?usage=history'),
  listReferences: () => api.get<FarmReferenceOptionsResponse>('/farms/reference-options'),
  listFarms: () => api.get<FarmResponse[]>('/farms'),
  getFarm: (farmId: string) => api.get<FarmResponse>(`/farms/${encodeURIComponent(farmId)}`),
  createFarm: (input: FarmCreateInput) => api.post<FarmResponse>('/farms', input),
  updateFarm: (farmId: string, input: Partial<FarmCreateInput>) => api.patch<FarmResponse>(
    `/farms/${encodeURIComponent(farmId)}`,
    input,
  ),
  retryEnvironmentalContext: (farmId: string) => api.post<EnvironmentalContextResponse>(
    `/farms/${encodeURIComponent(farmId)}/environmental-context`,
    { force_refresh: true },
  ),
};
