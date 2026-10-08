/** Mirror of web/sar/models.py; optional additive fields permit staged controller integration. */
export interface Metric {
  id: string;
  name: string;
  unit: string | null;
  target: string | null;
  assay: string | null;
}
export interface Observation {
  metric_id: string;
  value: string;
  unit: string | null;
  context: Record<string, string | null>;
  source_page: number | null;
  source_row: number | null;
  source_kind: 'patent' | 'imported' | 'manual';
}
export interface Molecule {
  id: string;
  label: string;
  smiles: string | null;
  molfile: string | null;
  graph_sha256: string | null;
  eligible: boolean;
  issues: string[];
  observations: Observation[];
  source_compound_id: string | null;
  source_page: number | null;
}
export interface Dataset {
  id: string;
  title: string;
  source_kind: 'project' | 'csv';
  source_project_id: string | null;
  source_sha256: string;
  source_document_sha256?: string | null;
  revision: number;
  stale: boolean;
  row_count: number;
  input_row_count?: number;
  eligible_count: number;
  issue_count: number;
  metrics: Metric[];
  created_at: string;
}
export interface DatasetList {
  items: Dataset[];
  total: number;
}
export interface MoleculePage {
  items: Molecule[];
  total: number;
  page: number;
  page_size: number;
}
export interface CSVPreview {
  token: string;
  filename: string;
  headers: string[];
  row_count: number;
  samples: Record<string, string>[];
  suggested_id: string | null;
  suggested_smiles: string | null;
  suggested_activities: string[];
}
export interface CSVMapping {
  token: string;
  title: string;
  id_column: string;
  smiles_column: string;
  activity_columns: string[];
  metric_column?: string | null;
  assay_column: string | null;
  target_column: string | null;
  unit_column: string | null;
  cell_line_column: string | null;
  duration_column: string | null;
  request_id: string;
}
export interface ProjectSnapshot {
  project_id: string;
  title: string | null;
  request_id: string;
}
export interface Atom {
  index: number;
  element: string;
  x: number;
  y: number;
}
export interface MoleculeDrawing {
  molecule: Molecule;
  svg: string;
  atoms: Atom[];
}
export interface RegionRequest {
  molecule_id: string;
  expected_dataset_revision: number;
  expected_graph_sha256: string;
  atom_indices: number[];
}
export interface Region {
  id: string;
  dataset_id: string;
  molecule_id: string;
  dataset_revision: number;
  graph_sha256: string;
  atom_indices: number[];
  attachment_count: number;
  created_at: string;
}
export interface AnalysisRequest {
  request_id: string;
  expected_dataset_revision: number;
  region_id: string;
  metric_id: string;
  direction: 'lower' | 'higher';
  grade_order: string[];
  confirm_context: boolean;
}
export type JobState = 'queued' | 'running' | 'complete' | 'failed' | 'cancelled' | 'interrupted';
export interface SARJob {
  id: string;
  dataset_id: string;
  region_id: string;
  metric_id: string;
  status: JobState;
  processed: number;
  total: number;
  matched: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  input_sha256: string;
  stale: boolean;
}
export interface JobList {
  items: SARJob[];
  total: number;
}
export type MatchState = 'matched' | 'not_matched' | 'ambiguous' | 'ineligible';
export type Comparison =
  'better' | 'worse' | 'equal' | 'indeterminate' | 'missing' | 'context_mismatch';
export interface Pair {
  reference_id: string;
  molecule_id: string;
  label: string;
  match_status: MatchState;
  reasons: string[];
  comparison: Comparison;
  reference_values: string[];
  candidate_values: string[];
  fold_change: number | null;
  evidence_basis: 'recorded_context' | 'user_confirmed' | 'insufficient';
}
export interface PairPage {
  items: Pair[];
  total: number;
  page: number;
  page_size: number;
  job: SARJob;
}
export interface ResumeRequest {
  expected_input_sha256: string;
}
