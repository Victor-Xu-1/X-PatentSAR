import type { Project } from './types';
export interface AdmetResult {
  engine: { name: string; version: string | number; model_sha256: string };
  generated_at: string;
  review_only: true;
  predictions: {
    smiles: string;
    properties: {
      key: string;
      label: string;
      value: number;
      unit: string | null;
      kind: 'descriptor' | 'prediction';
    }[];
  }[];
  warnings: string[];
}
export interface RecognitionResult {
  compound_id: string;
  status: 'recognized' | 'rejected';
  smiles: string | null;
  engine: { name: string; version: string | number };
  warnings: string[];
  review_only: true;
}
export interface EvidenceSummary {
  project_id: string;
  generated_at: string;
  acceptance: Project['acceptance'];
  counts: {
    structures: number;
    activity_rows: number;
    compounds: number;
    smiles: number;
    source_located: number;
    needs_review: number;
  };
  activities: {
    name: string;
    unit: string | null;
    rows: number;
    numeric_rows: number;
    min: number | null;
    max: number | null;
    censored_rows: number;
    target: string | null;
  }[];
  targets: { name: string; rows: number }[];
  limitations: string[];
  source_pages: number[];
}
