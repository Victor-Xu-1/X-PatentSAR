import type { Compound, Health, Job, PageData, Project, Results, Session } from '../src/api/types';
import { stageNames } from '../src/api/types';
// Isolated contract inputs only. Never imported by production source or used as API fallback.
export const session: Session = { csrf_token: 'contract-only-csrf', user: { name: '本地测试' } };
export const health: Health = {
  product: { name: 'X-PatentSAR', version: '0.1.0' },
  schema: { name: 'patentsar.web-api', version: 1 },
  ruleset: { name: 'patentsar.accuracy-first', version: '2.0.1' },
  ready: true,
  capabilities: { admet: false, summary: false },
};
export const project: Project = {
  id: 'project-contract',
  title: '契约测试专利',
  patent_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  pdf: { available: true, page_count: 12, sha256: null },
  is_historical: false,
  summary: {
    structures: 2,
    activity_rows: 2,
    matched_structures: 1,
    confirmed: 1,
    needs_review: 1,
  },
  acceptance: { state: 'not_run', errors: [] },
};
export const compound: Compound = {
  id: 'I-7',
  display_id: 'I-7',
  structure_id: 'structure-contract',
  structure_image_url: '/api/v1/projects/project-contract/structures/I-7/image',
  smiles: null,
  activities: [
    {
      name: '抑制等级',
      value: '++',
      unit: null,
      target: '测试靶点',
      assay: '契约隔离实验',
      page: 5,
    },
  ],
  source: {
    page: 4,
    paragraph: '[0007]',
    bbox: [10, 20, 80, 70],
    source_label: 'I-7',
    correction_reason: null,
  },
  confidence: { level: 'unknown', score: null, reason: '历史契约证据' },
  review: null,
  flags: ['historical'],
};
export const results: Results = {
  items: [compound],
  total: 1,
  page: 1,
  page_size: 10,
  metrics: ['抑制等级'],
  targets: ['测试靶点'],
};
export const page: PageData = {
  page: 4,
  page_count: 12,
  width: 200,
  height: 300,
  image_url: '/api/v1/projects/project-contract/pages/4/image',
  text: '<script>untrusted OCR</script>',
  source_mode: 'native',
  annotations: [
    { compound_id: compound.id, bbox: [10, 20, 80, 70], kind: 'structure', verified: false },
  ],
};
export const job: Job = {
  id: 'job-contract',
  project_id: project.id,
  status: 'running',
  created_at: '2026-01-01T00:00:00Z',
  started_at: null,
  finished_at: null,
  error: null,
  stages: stageNames.map((name) => ({
    name,
    status: name === 'classify' ? 'running' : 'pending',
    count: null,
    duration_seconds: null,
  })),
  can_resume: false,
  include_intermediates: false,
  force: false,
  task_note: '',
};
export function json(input: unknown, status = 200) {
  return new Response(JSON.stringify(input), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
