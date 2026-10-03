import {
  array,
  boolean,
  ContractError,
  count,
  defaulted,
  nullable,
  number,
  object,
  oneOf,
  positive,
  scalar,
  string,
} from './validation';
import type {
  BBox,
  Compound,
  CompoundRecognition,
  Health,
  Job,
  PageData,
  Project,
  Results,
  Review,
  Runtime,
  Session,
  StageProgress,
} from './types';
import { stageNames } from './types';
import type { Decoder } from './validation';

const identity = object({ name: string, version: scalar });
const capabilities = object({ admet: boolean, summary: boolean });
const bbox: Decoder<BBox> = (v, p = '$') => {
  const a = array(number)(v, p);
  if (a.length !== 4) throw new ContractError(p);
  const [x1, y1, x2, y2] = a as BBox;
  if (x1 < 0 || y1 < 0 || x2 <= x1 || y2 <= y1) throw new ContractError(p);
  return [x1, y1, x2, y2];
};
const score: Decoder<number> = (v, p) => {
  const n = number(v, p);
  if (n < 0 || n > 1) throw new ContractError(p ?? '$');
  return n;
};
const tokenConfidenceShape = object({ minimum: score, mean: score });
const tokenConfidence: Decoder<{ minimum: number; mean: number }> = (input, path) => {
  const value = tokenConfidenceShape(input, path);
  if (value.minimum > value.mean) throw new ContractError(path ?? '$');
  return value;
};
const recognition: Decoder<CompoundRecognition> = object({
  status: oneOf(['not_run', 'valid', 'invalid', 'unavailable']),
  quality_flag: nullable(string),
  model_fingerprint: nullable(string),
  token_confidence: nullable(tokenConfidence),
});
const nonnegative: Decoder<number> = (input, path) => {
  const value = number(input, path);
  if (value < 0) throw new ContractError(path ?? '$');
  return value;
};
const progressShape = object({
  completed: count,
  total: count,
  cache_hits: count,
  failures: count,
  device: nullable(oneOf(['cpu', 'gpu'])),
  peak_rss_mb: nullable(nonnegative),
});
const progress: Decoder<StageProgress> = (input, path) => {
  const value = progressShape(input, path);
  if (value.completed > value.total) throw new ContractError(path ?? '$');
  return value;
};
const healthShape = object({
  product: identity,
  schema: identity,
  ruleset: identity,
  ready: boolean,
  capabilities,
});
export const decodeHealth: Decoder<Health> = (input, path) => {
  const health = healthShape(input, path);
  if (
    health.product.name !== 'X-PatentSAR' ||
    health.schema.name !== 'patentsar.web-api' ||
    health.schema.version !== 1
  )
    throw new ContractError('$.schema.identity');
  return health;
};
export const decodeSession: Decoder<Session> = object({
  csrf_token: string,
  user: object({ name: string }),
});
export const decodeProject: Decoder<Project> = object({
  id: string,
  title: string,
  patent_id: nullable(string),
  created_at: string,
  updated_at: string,
  pdf: object({ available: boolean, page_count: count, sha256: nullable(string) }),
  is_historical: boolean,
  summary: object({
    structures: count,
    activity_rows: count,
    matched_structures: count,
    confirmed: count,
    needs_review: count,
    manually_reviewed: nullable(count),
    manual_review_pending: nullable(count),
  }),
  acceptance: object({
    state: oneOf(['not_run', 'accepted', 'failed', 'historical']),
    errors: array(string),
  }),
});
export const decodeReview: Decoder<Review> = object({
  decision: oneOf(['approved', 'rejected', 'needs_review']),
  note: string,
  revision: count,
  updated_at: string,
});
export const decodeCompound: Decoder<Compound> = object({
  id: string,
  display_id: string,
  structure_id: nullable(string),
  structure_image_url: nullable(string),
  redraw_image_url: nullable(string),
  smiles: nullable(string),
  recognition: nullable(recognition),
  activities: array(
    object({
      name: string,
      value: nullable(scalar),
      unit: nullable(string),
      target: nullable(string),
      assay: nullable(string),
      page: nullable(positive),
    }),
  ),
  source: object({
    page: nullable(positive),
    paragraph: nullable(scalar),
    bbox: nullable(bbox),
    source_label: nullable(string),
    correction_reason: nullable(string),
  }),
  confidence: object({
    level: oneOf(['high', 'medium', 'review', 'unknown']),
    score: nullable(score),
    reason: nullable(string),
  }),
  review: nullable(decodeReview),
  flags: array(string),
});
export const decodePage: Decoder<PageData> = object({
  page: positive,
  page_count: positive,
  width: nullable(number),
  height: nullable(number),
  image_url: nullable(string),
  text: string,
  source_mode: oneOf(['native', 'ocr', 'historical', 'unavailable']),
  annotations: array(object({ compound_id: string, bbox, kind: string, verified: boolean })),
});
export const decodeJob: Decoder<Job> = object({
  id: string,
  project_id: string,
  status: oneOf(['queued', 'running', 'complete', 'failed', 'cancelled', 'interrupted']),
  created_at: string,
  started_at: nullable(string),
  finished_at: nullable(string),
  error: nullable(object({ code: string, message: string })),
  can_resume: boolean,
  history_available: nullable(boolean),
  include_intermediates: defaulted(boolean, false),
  force: defaulted(boolean, false),
  task_note: defaulted(string, ''),
  stages: array(
    object({
      name: oneOf(stageNames),
      status: oneOf(['pending', 'running', 'ok', 'empty', 'failed', 'warnings']),
      count: nullable(count),
      duration_seconds: nullable(number),
      progress: nullable(progress),
      reused_checkpoint: nullable(boolean),
    }),
  ),
});
export const decodeResults: Decoder<Results> = object({
  items: array(decodeCompound),
  total: count,
  page: positive,
  page_size: positive,
  metrics: array(string),
  targets: array(string),
});
export const decodeRuntime: Decoder<Runtime> = object({
  product: identity,
  storage: object({ state_root: string, platform: string }),
  interpreters: array(object({ role: string, configured: boolean, available: boolean })),
  capabilities,
});
export const decodeProjects = object({ items: array(decodeProject) });
export const decodeJobs = object({ items: array(decodeJob) });
