import type { AdmetResult, EvidenceSummary, RecognitionResult } from '../src/api/analysisTypes';
import { project } from './fixtures';
// Test-only contract inputs; no prediction fixture is used in production.
export const admet: AdmetResult = {
  engine: { name: 'ADMET-AI', version: '2', model_sha256: 'a'.repeat(64) },
  generated_at: '2026-01-01T00:00:00Z',
  review_only: true,
  predictions: [
    {
      smiles: 'CCO',
      properties: [
        {
          key: 'molecular_weight',
          label: '分子量',
          value: 46.069,
          unit: 'g/mol',
          kind: 'descriptor',
        },
        { key: 'endpoint', label: '测试端点', value: 0.2, unit: 'probability', kind: 'prediction' },
      ],
    },
  ],
  warnings: [],
};
export const recognized: RecognitionResult = {
  compound_id: 'I-7',
  status: 'recognized',
  smiles: 'CCO',
  engine: { name: 'DECIMER', version: '2.8.0' },
  warnings: [],
  review_only: true,
};
export const evidence: EvidenceSummary = {
  project_id: project.id,
  generated_at: '2026-01-01T00:00:00Z',
  acceptance: project.acceptance,
  counts: {
    structures: 2,
    activity_rows: 3,
    compounds: 2,
    smiles: 1,
    source_located: 2,
    needs_review: 1,
  },
  activities: [
    {
      name: 'IC50',
      unit: 'nM',
      rows: 2,
      numeric_rows: 1,
      min: 12,
      max: 12,
      censored_rows: 1,
      target: 'A',
    },
    {
      name: 'IC50',
      unit: 'µM',
      rows: 1,
      numeric_rows: 1,
      min: 0.5,
      max: 0.5,
      censored_rows: 0,
      target: 'B',
    },
  ],
  targets: [
    { name: 'A', rows: 2 },
    { name: 'B', rows: 1 },
  ],
  limitations: ['范围和删失值不参与精确数值极值统计'],
  source_pages: [4, 5],
};
