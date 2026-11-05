import { api } from './client';
import type { ContextPeriod, EnvironmentalIndicator, PriorityPoints } from './farms';

export interface ClimateFeature {
  feature_key: string;
  method_version: string;
  status: string;
  reason?: string | null;
  crop_id: string;
  stage_key: string;
  evidence_status: string;
  exposure_min_days: number | null;
  exposure_max_days: number | null;
  units: string;
  reference_start_year: number;
  reference_end_year: number;
  source_snapshot_id: string | null;
  source_products: string[];
  spatial_resolution?: string | null;
  dry_day_definition?: string;
  feasible_placement_count?: number;
  complete_years_per_placement?: number;
  interpretation: string;
}

export interface SnapshotUseProvenance {
  snapshot_id: string | null;
  start_date: string;
  end_date: string;
  data_status: 'live' | 'cached' | 'unavailable';
  cache_action: string;
  freshness_status: 'fresh' | 'stale' | 'unknown';
  retrieved_at: string | null;
  source_products: string[];
  parameters: {
    code: string;
    units: string;
    source: string | null;
    spatial_resolution: string | null;
    expected_days: number;
    valid_days: number;
    missing_days: number;
  }[];
  warning_codes: string[];
}

export interface CandidateEvent {
  event: {
    season_label?: string;
    window_start?: string | null;
    window_end?: string | null;
    harvest_start?: string | null;
    harvest_end?: string | null;
    calendar_status?: string;
    calendar_source?: string | null;
    calendar_source_version?: string | null;
    review_reasons?: string[];
  };
  crop: { crop_id: string; display_name: string };
}

export interface ScoredOption {
  candidate: { candidate_id: string; events: CandidateEvent[]; readiness: string };
  criteria: {
    criterion: string;
    status: string;
    rating: string | null;
    confidence: string | null;
    selected_weight_percent?: number | string | null;
    rationale: string;
    evidence_references: string[];
    environmental_inputs: EnvironmentalIndicator[];
    assumptions: string[];
  }[];
  benefits: string[];
  trade_offs: string[];
  assumptions: string[];
  warnings: string[];
}

export interface UnrankedCalendarExample {
  candidate_id: string;
  status: 'unranked_needs_review';
  events: CandidateEvent[];
  review_reasons: string[];
  selection_note: string;
}

export interface RankingOutcome {
  status: string;
  criteria_used: string[];
  rank_groups: string[][];
  reasons: string[];
  provisional: boolean;
  tradeoffs: { explanation: string; higher_ranked_candidate_id: string; lower_ranked_candidate_id: string }[];
  climate_tie_preferences?: { explanation: string; metric_key: string; policy_version: string }[];
}

export interface WeightProfileResponse {
  source: string;
  normalized_weights: { criterion: string; percent: number | string }[];
}

export interface RotationResultResponse {
  id: string;
  farm_id: string;
  schema_version: string;
  created_at: string;
  decision_status?: string;
  baseline_status?: string;
  derived_context_period?: ContextPeriod | null;
  history_event_snapshots?: {
    event_id: string;
    crop_key: string;
    sequence_order: number;
    start_date: string | null;
    end_date: string | null;
    variety_key: string | null;
    production_system_key: string | null;
  }[];
  context_provenance?: SnapshotUseProvenance | null;
  climate_reference_provenance?: SnapshotUseProvenance | null;
  indicators?: EnvironmentalIndicator[];
  climate_features?: ClimateFeature[];
  climate_feature_status_reason?: string | null;
  future_window_summary?: {
    candidate_count: number;
    fully_scheduled_count: number;
    needs_review_count: number;
    review_reasons: string[];
  } | null;
  unranked_calendar_examples?: UnrankedCalendarExample[];
  environmental_snapshot_ids?: string[];
  scoring_result: {
    scoring_version: string;
    ranking_mode: string | null;
    provisional: boolean;
    options: ScoredOption[];
    ranking: RankingOutcome | null;
    equal_weight_ranking?: RankingOutcome | null;
    selected_weight_ranking?: RankingOutcome | null;
    sensitivity?: string | null;
    default_weights?: WeightProfileResponse | null;
    selected_weights?: WeightProfileResponse | null;
  };
}

export const recommendationApi = {
  listForFarm: (farmId: string) => api.get<RotationResultResponse[]>(
    `/farms/${encodeURIComponent(farmId)}/rotation-results`,
  ),
  generateForFarm: (farmId: string, priorityAdjustment?: PriorityPoints) => api.post<RotationResultResponse>(
    `/farms/${encodeURIComponent(farmId)}/rotation-recommendations`,
    priorityAdjustment ? { priority_adjustment: priorityAdjustment } : {},
  ),
};
