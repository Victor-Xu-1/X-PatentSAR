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
  Activity,
  Compound,
  CompoundRecognition,
  Health,
  Job,
  Project,
  Results,
  Review,
  Runtime,
  Session,
} from './types';
import { recordKinds, stageNames } from './types';
import type { Decoder } from './validation';
import { decodeDescriptorSummary, decodePredictionSummary } from './predictionDecoders';
import { decodeAdmetStage, decodeCoreStage, decodeStageOrder } from './stageDecoders';
import { activityContextKey, decodeActivityColumns } from './activityColumnDecoders';
import { decodeBBox as bbox } from './geometryDecoders';
import { decodeActivitySourceKeys } from './activitySourceDecoders';
import { decodeActivityRankValues } from './activityRankDecoders';
import { decodeMolfile, decodePropertyOverrides } from './correctionDecoders';
import { decodeStereoEvidence } from './stereoDecoders';
import { decodeLeadAssessment } from './leadDecoders';
export { decodePage } from './pageDecoders';

const identity = object({ name: string, version: scalar });
const capabilities = object({ admet: boolean, summary: boolean });
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
  stereochemistry: nullable(decodeStereoEvidence),
});
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
const projectShape = object({
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
export const decodeProject: Decoder<Project> = (input, path = '$') => {
  const project = projectShape(input, path);
  const fields = input as Record<string, unknown>;
  const rawSummary = fields.summary as Record<string, unknown>;
  const summary = {
    ...project.summary,
    ...(Object.hasOwn(rawSummary, 'structure_only')
      ? {
          structure_only: nullable(count)(
            rawSummary.structure_only,
            path + '.summary.structure_only',
          ),
        }
      : {}),
    ...(Object.hasOwn(rawSummary, 'activity_only')
      ? {
          activity_only: nullable(count)(rawSummary.activity_only, path + '.summary.activity_only'),
        }
      : {}),
  };
  if (!Object.hasOwn(fields, 'first_structure_page')) return { ...project, summary };
  const first = nullable(positive)(fields.first_structure_page, `${path}.first_structure_page`);
  if (first !== null && project.pdf.page_count > 0 && first > project.pdf.page_count)
    throw new ContractError(`${path}.first_structure_page`);
  return { ...project, summary, first_structure_page: first };
};
export const decodeReview: Decoder<Review> = object({
  decision: oneOf(['approved', 'rejected', 'needs_review']),
  note: string,
  revision: count,
  updated_at: string,
});
export const activityDecoder: Decoder<Activity> = object({
  name: string,
  value: nullable(scalar),
  unit: nullable(string),
  target: nullable(string),
  assay: nullable(string),
  page: nullable(positive),
});
const correctionMetadata = object({
  revision: positive,
  stale: boolean,
  has_changes: boolean,
  updated_at: string,
});
const compoundShape = object({
  id: string,
  display_id: string,
  structure_id: nullable(string),
  structure_image_url: nullable(string),
  redraw_image_url: nullable(string),
  smiles: nullable(string),
  recognition: nullable(recognition),
  activities: array(activityDecoder),
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
export const decodeCompound: Decoder<Compound> = (input, path = '$') => {
  const compound = compoundShape(input, path);
  const fields = input as Record<string, unknown>;
  return {
    ...compound,
    ...(Object.hasOwn(fields, 'identifier_label') ? { identifier_label: nullable(string)(fields.identifier_label, `${path}.identifier_label`) } : {}),
    ...(Object.hasOwn(fields, 'structure_molfile')
      ? {
          structure_molfile: nullable(decodeMolfile)(
            fields.structure_molfile,
            `${path}.structure_molfile`,
          ),
        }
      : {}),
    ...(Object.hasOwn(fields, 'property_overrides')
      ? {
          property_overrides: decodePropertyOverrides(
            fields.property_overrides,
            `${path}.property_overrides`,
          ),
        }
      : {}),
    ...(Object.hasOwn(fields, 'additional_sources')
      ? {
          additional_sources: array(
            object({
              page: nullable(positive),
              paragraph: nullable(scalar),
              bbox: nullable(bbox),
              source_label: nullable(string),
              correction_reason: nullable(string),
            }),
          )(fields.additional_sources, `${path}.additional_sources`),
        }
      : {}),
    ...(Object.hasOwn(fields, 'activity_rank_values')
      ? {
          activity_rank_values: decodeActivityRankValues(
            fields.activity_rank_values,
            compound.activities.length,
            `${path}.activity_rank_values`,
          ),
        }
      : {}),
    ...(Object.hasOwn(fields, 'activity_source_keys')
      ? {
          activity_source_keys: decodeActivitySourceKeys(
            fields.activity_source_keys,
            compound.activities.length,
            path + '.activity_source_keys',
          ),
        }
      : {}),
    ...(Object.hasOwn(fields, 'record_kind')
      ? { record_kind: nullable(oneOf(recordKinds))(fields.record_kind, path + '.record_kind') }
      : {}),
    ...(Object.hasOwn(fields, 'admet')
      ? { admet: nullable(decodePredictionSummary)(fields.admet, `${path}.admet`) }
      : {}),
    ...(Object.hasOwn(fields, 'descriptors')
      ? {
          descriptors: nullable(decodeDescriptorSummary)(fields.descriptors, `${path}.descriptors`),
        }
      : {}),
    ...(Object.hasOwn(fields, 'lead')
      ? { lead: nullable(decodeLeadAssessment)(fields.lead, `${path}.lead`) }
      : {}),
    ...(Object.hasOwn(fields, 'correction')
      ? { correction: nullable(correctionMetadata)(fields.correction, `${path}.correction`) }
      : {}),
  };
};
const jobShape = object({
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
  stages: array(decodeCoreStage),
});
export const decodeJob: Decoder<Job> = (input, path = '$') => {
  const job = jobShape(input, path);
  const fields = input as Record<string, unknown>;
  const result: Job = {
    ...job,
    ...(Object.hasOwn(fields, 'include_admet')
      ? { include_admet: boolean(fields.include_admet, `${path}.include_admet`) }
      : {}),
    ...(Object.hasOwn(fields, 'admet_only')
      ? { admet_only: boolean(fields.admet_only, `${path}.admet_only`) }
      : {}),
    ...(Object.hasOwn(fields, 'admet_stage')
      ? { admet_stage: nullable(decodeAdmetStage)(fields.admet_stage, `${path}.admet_stage`) }
      : {}),
    ...(Object.hasOwn(fields, 'stage_order')
      ? { stage_order: nullable(decodeStageOrder)(fields.stage_order, `${path}.stage_order`) }
      : {}),
  };
  if (
    (result.admet_stage != null && result.include_admet !== true) ||
    (result.admet_only === true && (result.include_admet !== true || result.stages.length > 0))
  )
    throw new ContractError(path);
  if (
    result.stage_order != null &&
    result.stage_order.length !== (result.admet_only === true ? 0 : stageNames.length)
  )
    throw new ContractError(`${path}.stage_order`);
  return result;
};
const resultsShape = object({
  items: array(decodeCompound),
  total: count,
  page: positive,
  page_size: positive,
  metrics: array(string),
  targets: array(string),
});
export const decodeResults: Decoder<Results> = (input, path = '$') => {
  const result = resultsShape(input, path);
  if (input === null || typeof input !== 'object') throw new ContractError(path);
  const fields = input as Record<string, unknown>;
  if (!Object.hasOwn(fields, 'activity_columns')) return result;
  const activity_columns = decodeActivityColumns(
    fields.activity_columns,
    `${path}.activity_columns`,
  );
  const contexts = new Set(activity_columns.map(activityContextKey));
  if (
    result.items.some((item) =>
      item.activities.some((value) => !contexts.has(activityContextKey(value))),
    )
  )
    throw new ContractError(`${path}.activity_columns`);
  return { ...result, activity_columns };
};
export const decodeRuntime: Decoder<Runtime> = object({
  product: identity,
  storage: object({ state_root: string, platform: string }),
  interpreters: array(object({ role: string, configured: boolean, available: boolean })),
  capabilities,
});
export const decodeProjects = object({ items: array(decodeProject) });
export const decodeJobs = object({ items: array(decodeJob) });
