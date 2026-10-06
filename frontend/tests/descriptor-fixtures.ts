import { METRIC_SPECS } from '../src/api/predictionTypes';

// Isolated producer contract observations; never loaded by the application.
export const descriptorSummary = {
  status: 'complete' as const,
  properties: METRIC_SPECS.slice(0, 5).map((spec, index) => ({
    ...spec,
    value: [46.069, -0.1, 20.23, 1, 1][index]!,
  })),
  source_fingerprint: '1'.repeat(64),
  smiles_sha256: '2'.repeat(64),
  engine: { name: 'RDKit' as const, version: '2025.09.6', algorithm_sha256: '3'.repeat(64) },
  generated_at: '2026-10-07T01:00:00Z',
  job_id: '4'.repeat(32),
  error: null,
  review_only: true as const,
};
export function incompleteDescriptors(status: string) {
  return {
    ...descriptorSummary,
    status,
    properties: [],
    engine: null,
    generated_at: null,
    error:
      status === 'failed' ? { code: 'descriptor_failed', message: 'RDKit producer failed' } : null,
  };
}

export const predictionSummary = {
  ...descriptorSummary,
  properties: METRIC_SPECS.map((spec, index) => ({
    ...spec,
    value: [46.069, -0.1, 20.23, 1, 1, -3.2][index]!,
  })),
  engine: { name: 'ADMET-AI', version: '2.0.1', model_sha256: '5'.repeat(64) },
  warnings: [],
};
