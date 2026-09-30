import {
  array,
  ContractError,
  count,
  nullable,
  number,
  object,
  oneOf,
  positive,
  scalar,
  string,
} from './validation';
import type { Decoder } from './validation';
import type { AdmetResult, EvidenceSummary, RecognitionResult } from './analysisTypes';
const reviewOnly: Decoder<true> = (value, path = '$') => {
  if (value !== true) throw new ContractError(path);
  return true;
};
const nonempty: Decoder<string> = (value, path = '$') => {
  const text = string(value, path);
  if (!text.trim()) throw new ContractError(path);
  return text;
};
const modelSha: Decoder<string> = (value, path = '$') => {
  const sha = string(value, path);
  if (!/^[a-f0-9]{64}$/i.test(sha)) throw new ContractError(path);
  return sha;
};
const admetShape = object({
  engine: object({ name: nonempty, version: scalar, model_sha256: modelSha }),
  generated_at: string,
  review_only: reviewOnly,
  predictions: array(
    object({
      smiles: nonempty,
      properties: array(
        object({
          key: nonempty,
          label: string,
          value: number,
          unit: nullable(string),
          kind: oneOf(['descriptor', 'prediction']),
        }),
      ),
    }),
  ),
  warnings: array(string),
});
export const decodeAdmet: Decoder<AdmetResult> = (value, path) => {
  const result = admetShape(value, path);
  if (result.predictions.length < 1 || result.predictions.length > 50)
    throw new ContractError('$.predictions');
  return result;
};
const recognitionShape = object({
  compound_id: nonempty,
  status: oneOf(['recognized', 'rejected']),
  smiles: nullable(nonempty),
  engine: object({ name: nonempty, version: scalar }),
  warnings: array(string),
  review_only: reviewOnly,
});
export const decodeRecognition: Decoder<RecognitionResult> = (value, path) => {
  const result = recognitionShape(value, path);
  if (result.status === 'recognized' && !result.smiles) throw new ContractError('$.smiles');
  return result;
};
const summaryShape = object({
  project_id: nonempty,
  generated_at: string,
  acceptance: object({
    state: oneOf(['not_run', 'accepted', 'failed', 'historical']),
    errors: array(string),
  }),
  counts: object({
    structures: count,
    activity_rows: count,
    compounds: count,
    smiles: count,
    source_located: count,
    needs_review: count,
  }),
  activities: array(
    object({
      name: string,
      unit: nullable(string),
      rows: count,
      numeric_rows: count,
      min: nullable(number),
      max: nullable(number),
      censored_rows: count,
      target: nullable(string),
    }),
  ),
  targets: array(object({ name: string, rows: count })),
  limitations: array(string),
  source_pages: array(positive),
});
export const decodeEvidenceSummary: Decoder<EvidenceSummary> = (value, path) => {
  const summary = summaryShape(value, path);
  for (const activity of summary.activities) {
    if (
      activity.numeric_rows > activity.rows ||
      activity.censored_rows > activity.rows ||
      (activity.min !== null && activity.max !== null && activity.min > activity.max)
    )
      throw new ContractError('$.activities');
  }
  return summary;
};
