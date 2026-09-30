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
  summary: {
    structures: number;
    activity_rows: number;
    matched_structures: number;
    confirmed: number;
    needs_review: number;
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
export interface Compound {
  id: string;
  display_id: string;
  structure_id: string | null;
  structure_image_url: string | null;
  smiles: string | null;
  activities: Activity[];
  source: {
    page: number | null;
    paragraph: string | number | null;
    bbox: BBox | null;
    source_label: string | null;
    correction_reason: string | null;
  };
  confidence: { level: ConfidenceLevel; score: number | null; reason: string | null };
  review: Review | null;
  flags: string[];
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
export type StageName = (typeof stageNames)[number];
export type StageStatus = 'pending' | 'running' | 'ok' | 'empty' | 'failed' | 'warnings';
export interface Job {
  id: string;
  project_id: string;
  status: 'queued' | 'running' | 'complete' | 'failed' | 'cancelled' | 'interrupted';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: { code: string; message: string } | null;
  stages: {
    name: StageName;
    status: StageStatus;
    count: number | null;
    duration_seconds: number | null;
  }[];
  can_resume: boolean;
  include_intermediates: boolean;
  force: boolean;
  task_note: string;
}
export interface JobOptions {
  include_intermediates?: boolean;
  force?: boolean;
  task_note?: string;
}
export interface Results {
  items: Compound[];
  total: number;
  page: number;
  page_size: number;
  metrics: string[];
  targets: string[];
}
export interface Filters {
  q: string;
  confidence: string;
  review: string;
  target: string;
  page: number;
  page_size: number;
}
export interface Runtime {
  product: Identity;
  storage: { state_root: string; platform: string };
  interpreters: { role: string; configured: boolean; available: boolean }[];
  capabilities: { admet: boolean; summary: boolean };
}
