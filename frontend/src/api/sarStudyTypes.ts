/** Sole authority: web/sar/study_models.py. No locally inferred scientific fields. */
import type { Region, SARJob } from './sarTypes';
import type { Project } from './types';
export interface StudyContext {
  id: string;
  metric_id: string;
  name: string;
  unit: string | null;
  context: Record<string, string | null>;
  molecule_count: number;
  observation_count: number;
  distinct_value_count: number;
  value_samples: string[];
}
export interface StudyProfile {
  dataset_id: string;
  dataset_revision: number;
  contexts: StudyContext[];
  regions: Region[];
}
export interface StudyPolicy {
  context_id: string;
  direction: 'lower' | 'higher';
  grade_order: string[];
  strong_threshold: number | null;
  threshold_inclusive: boolean;
}
export interface StudyRequest {
  request_id: string;
  expected_dataset_revision: number;
  title: string;
  policies: StudyPolicy[];
  region_ids: string[];
  core_ids?: string[];
  confirm_context: boolean;
  candidate_count: number;
  context_declarations?: ConditionDeclaration[];
}
export interface ConditionDeclaration {
  context_id: string;
  fields: Partial<Record<'target' | 'assay' | 'cell_line' | 'duration', string>>;
  source_document_sha256: string;
  source_pages: number[];
  note: string;
}
export interface StudyBin {
  label: string;
  kind: string;
  observations: number;
  molecules: number;
  strong: boolean;
}
export interface StudyDistribution {
  context_id: string;
  bins: StudyBin[];
  observed_molecules: number;
  observations: number;
  missing_molecules: number;
  unresolved_molecules: number;
  strong_molecules: number;
}
export interface StudyScaffold {
  id: string;
  smiles: string | null;
  molecule_count: number;
  strong_count: number;
  bins: StudyBin[];
  molecule_ids: string[];
  descriptive_only: true;
  assignment_kind?: 'murcko' | 'confirmed_core';
  core_region_id?: string | null;
}
export interface StudyFragment {
  id: string;
  smiles: string;
  molecule_ids: string[];
  molecule_count: number;
  strong_count: number;
  bins: StudyBin[];
  better: number;
  worse: number;
  indeterminate: number;
  missing: number;
  is_reference: boolean;
}
export interface StudyRegionSummary {
  region: Region;
  reference_label: string;
  reference_fragment_id: string | null;
  fixed_background_sha256: string;
  matched: number;
  not_matched: number;
  ambiguous: number;
  ineligible: number;
  comparable: number;
  no_variation: boolean;
  fragments: StudyFragment[];
  independent_backgrounds: 1;
}
export interface StudyRow {
  molecule_id: string;
  label: string;
  eligible: boolean;
  scaffold_id: string | null;
  values: Record<string, string[]>;
  activity_status: Record<string, string>;
  strong: boolean;
  properties: Record<string, number | null>;
  property_origins: Record<string, string>;
  predictions: Record<string, number | null>;
  prediction_origin: string;
  pareto_front: number | null;
  candidate_status: 'selected' | 'not_selected' | 'unranked' | 'ineligible' | 'partial';
  priority_group: number | null;
  selection_order: number | null;
  coverage: number;
  reasons: string[];
}
export interface StudyReport {
  schema_version: 1;
  dataset_id: string;
  dataset_revision: number;
  title: string;
  input_sha256: string;
  engine_sha256: string;
  research_only: true;
  article_algorithm_reproduced: false;
  counting_contract?: 'legacy-per-bin-members' | 'unique-molecules-v2';
  source_acceptance?: Project['acceptance'] | null;
  context_declarations?: ConditionDeclaration[];
  molecule_count: number;
  eligible_count: number;
  observation_count: number;
  strict_pair_count: number;
  matched_pair_count?: number;
  comparable_pair_count?: number;
  contexts: StudyContext[];
  policies: StudyPolicy[];
  distributions: StudyDistribution[];
  scaffolds: StudyScaffold[];
  regions: StudyRegionSummary[];
  candidates: StudyRow[];
  rows: StudyRow[];
  warnings: string[];
  candidate_policy: string;
}
export interface StudyOverview {
  job: SARJob;
  report: StudyReport;
}
export interface StudyRows {
  items: StudyRow[];
  total: number;
  page: number;
  page_size: number;
  job: SARJob;
}
export interface StudyDrawing {
  id: string;
  svg: string;
}
export interface StudyFilter {
  query: string;
  scope: 'all' | 'strong' | 'leads';
  scaffold_id: string;
  region_id: string;
  fragment_id: string;
}
export type StudyDrawingKind = 'molecule' | 'scaffold' | 'fragment';
export type StudyExportFormat = 'csv' | 'json' | 'sdf' | 'html';
/** Mirrors prediction_models.METRIC_KEYS and lead_endpoints.LEAD_ENDPOINTS. */
export const sarPropertyKeys = [
  'molecular_weight',
  'logP',
  'tpsa',
  'hydrogen_bond_donors',
  'hydrogen_bond_acceptors',
  'Solubility_AqSolDB',
] as const;
export const sarPredictionKeys = [
  'hERG',
  'AMES',
  'DILI',
  'ClinTox',
  'HIA_Hou',
  'Bioavailability_Ma',
  'CYP1A2_Veith',
  'CYP2C9_Veith',
  'CYP2C19_Veith',
  'CYP2D6_Veith',
  'CYP3A4_Veith',
] as const;
