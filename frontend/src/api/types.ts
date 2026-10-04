import type { PredictionSummary } from './predictionTypes';
import type { PropertyOverrides } from './manualPropertyTypes';

export interface Identity {
  name: string;
  version: string | number;
}
export interface Health {
  product: Identity;
  schema: Identity;
  ruleset: Identity;
  ready: boolean;
  capabilities: { admet: boolean; summary: boolean };
}
export interface Session {
  csrf_token: string;
  user: { name: string };
}
export type AcceptanceState = 'not_run' | 'accepted' | 'failed' | 'historical';
export interface Project {
  id: string;
  title: string;
  patent_id: string | null;
  created_at: string;
  updated_at: string;
  pdf: { available: boolean; page_count: number; sha256: string | null };
  is_historical: boolean;
  first_structure_page?: number | null;
  summary: {
    structures: number;
    activity_rows: number;
    matched_structures: number;
    confirmed: number;
    needs_review: number;
    manually_reviewed: number | null;
    manual_review_pending: number | null;
    structure_only?: number | null;
    activity_only?: number | null;
  };
  acceptance: { state: AcceptanceState; errors: string[] };
}
export type ReviewDecision = 'approved' | 'rejected' | 'needs_review';
export interface Review {
  decision: ReviewDecision;
  note: string;
  revision: number;
  updated_at: string;
}
export type ConfidenceLevel = 'high' | 'medium' | 'review' | 'unknown';
export type BBox = [number, number, number, number];
export interface Activity {
  name: string;
  value: string | number | null;
  unit: string | null;
  target: string | null;
  assay: string | null;
  page: number | null;
}
export interface ActivityColumn {
  id: string;
  name: string;
  unit: string | null;
  target: string | null;
  assay: string | null;
  strength_scale?: ActivityStrengthScale | null;
  filter_values?: { value: string; count: number }[];
  filter_values_truncated?: boolean;
}
export interface ActivityStrengthScale {
  kind: 'numeric' | 'plus' | 'letter' | 'unknown';
  direction: 'lower' | 'higher' | 'unknown';
  rule: string;
  eligible: number;
  excluded: number;
  distinct: number;
  strong_boundary: number | null;
  medium_boundary: number | null;
}
export interface ActivityFocusSelection {
  compoundId: string;
  key: string;
}
export interface ActivityFocus {
  compound_id: string;
  activity_key: string;
  status: 'located' | 'page_only';
  boxes: BBox[];
  message: string | null;
}
export const recordKinds = ['structure_activity', 'structure_only', 'activity_only'] as const;
export type RecordKind = (typeof recordKinds)[number];
export interface Compound {
  id: string;
  display_id: string;
  structure_id: string | null;
  structure_image_url: string | null;
  redraw_image_url: string | null;
  smiles: string | null;
  structure_molfile?: string | null;
  property_overrides?: PropertyOverrides;
  recognition: CompoundRecognition | null;
  activities: Activity[];
  activity_source_keys?: string[];
  activity_rank_values?: (number | null)[];
  record_kind?: RecordKind | null;
  source: {
    page: number | null;
    paragraph: string | number | null;
    bbox: BBox | null;
    source_label: string | null;
    correction_reason: string | null;
  };
  additional_sources?: {
    page: number | null;
    paragraph: string | number | null;
    bbox: BBox | null;
    source_label: string | null;
    correction_reason: string | null;
  }[];
  confidence: { level: ConfidenceLevel; score: number | null; reason: string | null };
  review: Review | null;
  flags: string[];
  admet?: PredictionSummary | null;
  correction?: CorrectionMetadata | null;
}
export interface CorrectionMetadata {
  revision: number;
  stale: boolean;
  has_changes: boolean;
  updated_at: string;
}
export interface CompoundRecognition {
  status: 'not_run' | 'valid' | 'invalid' | 'unavailable';
  quality_flag: string | null;
  model_fingerprint: string | null;
  token_confidence: { minimum: number; mean: number } | null;
}
export interface PageData {
  page: number;
  page_count: number;
  width: number | null;
  height: number | null;
  image_url: string | null;
  text: string;
  source_mode: 'native' | 'ocr' | 'historical' | 'unavailable';
  annotations: { compound_id: string; bbox: BBox; kind: string; verified: boolean }[];
  activity_focus?: ActivityFocus | null;
}
export const stageNames = [
  'classify',
  'activity',
  'locate',
  'structures',
  'bind',
  'smiles',
  'final',
  'qa',
] as const;
export type CoreStageName = (typeof stageNames)[number];
export type StageName = CoreStageName | 'admet';
export type StageStatus = 'pending' | 'running' | 'ok' | 'empty' | 'failed' | 'warnings';
export interface StageProgress {
  completed: number;
  total: number;
  cache_hits: number;
  failures: number;
  device: 'cpu' | 'gpu' | null;
  peak_rss_mb: number | null;
}
export interface Stage {
  name: StageName;
  status: StageStatus;
  count: number | null;
  duration_seconds: number | null;
  progress: StageProgress | null;
  reused_checkpoint: boolean | null;
  skipped?: number;
}
export interface Job {
  id: string;
  project_id: string;
  status: 'queued' | 'running' | 'complete' | 'failed' | 'cancelled' | 'interrupted';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: { code: string; message: string } | null;
  stages: Stage[];
  history_available: boolean | null;
  can_resume: boolean;
  include_intermediates: boolean;
  force: boolean;
  task_note: string;
  include_admet?: boolean;
  admet_only?: boolean;
  admet_stage?: (Stage & { name: 'admet' }) | null;
}
export interface JobOptions {
  include_intermediates?: boolean;
  force?: boolean;
  task_note?: string;
  include_admet?: boolean;
  admet_only?: boolean;
}
export interface Results {
  items: Compound[];
  total: number;
  page: number;
  page_size: number;
  metrics: string[];
  targets: string[];
  activity_columns?: ActivityColumn[];
}
export interface Filters {
  q: string;
  confidence: string;
  review: string;
  target: string;
  page: number;
  page_size: number;
  column_filters?: ColumnFilter[];
  sort_column?: string;
  sort_direction?: 'asc' | 'desc';
}
export interface ColumnFilter {
  column: string;
  op: 'contains' | 'eq' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'empty' | 'not_empty';
  value?: string;
  values?: string[];
}
export interface Runtime {
  product: Identity;
  storage: { state_root: string; platform: string };
  interpreters: { role: string; configured: boolean; available: boolean }[];
  capabilities: { admet: boolean; summary: boolean };
}
