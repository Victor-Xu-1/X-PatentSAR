export const METRIC_SPECS = [
  { key: 'molecular_weight', label: 'MW', unit: 'Dalton', kind: 'descriptor' },
  { key: 'logP', label: 'LogP', unit: 'log-ratio', kind: 'descriptor' },
  { key: 'tpsa', label: 'TPSA', unit: 'Å^2', kind: 'descriptor' },
  { key: 'hydrogen_bond_donors', label: 'HBD', unit: '#', kind: 'descriptor' },
  { key: 'hydrogen_bond_acceptors', label: 'HBA', unit: '#', kind: 'descriptor' },
  { key: 'Solubility_AqSolDB', label: 'LogS', unit: 'log(mol/L)', kind: 'prediction' },
] as const;
export type MetricKey = (typeof METRIC_SPECS)[number]['key'];
export const METRIC_KEYS: readonly MetricKey[] = METRIC_SPECS.map((metric) => metric.key);
export const DESCRIPTOR_KEYS: readonly MetricKey[] = METRIC_SPECS.filter(
  (metric) => metric.kind === 'descriptor',
).map((metric) => metric.key);

export interface PredictionMetric {
  key: MetricKey;
  label: string;
  value: number;
  unit: string;
  kind: 'descriptor' | 'prediction';
}
export interface PredictionEngine {
  name: string;
  version: string;
  model_sha256: string;
}
export type PredictionStatus =
  'not_run' | 'pending' | 'running' | 'complete' | 'failed' | 'stale' | 'unavailable';
export interface PredictionSummary {
  status: PredictionStatus;
  properties: PredictionMetric[];
  source_fingerprint: string | null;
  smiles_sha256: string | null;
  engine: PredictionEngine | null;
  generated_at: string | null;
  job_id: string | null;
  warnings: string[];
  error: { code: string; message: string } | null;
  review_only: true;
}
export interface DescriptorEngine {
  name: 'RDKit';
  version: string;
  algorithm_sha256: string;
}
export interface DescriptorSummary extends Omit<PredictionSummary, 'engine' | 'warnings'> {
  engine: DescriptorEngine | null;
}
