import { DESCRIPTOR_KEYS, METRIC_KEYS, METRIC_SPECS } from './predictionTypes';
import type {
  DescriptorSummary,
  MetricKey,
  PredictionMetric,
  PredictionSummary,
} from './predictionTypes';
import { array, ContractError, nullable, number, object, oneOf, string } from './validation';
import type { Decoder } from './validation';

function boundedText(max: number): Decoder<string> {
  return (input, path = '$') => {
    const text = string(input, path);
    if (!text.trim() || text.length > max) throw new ContractError(path);
    return text;
  };
}
function boundedArray<T>(decode: Decoder<T>, max: number): Decoder<T[]> {
  const read = array(decode);
  return (input, path = '$') => {
    if (!Array.isArray(input) || input.length > max) throw new ContractError(path);
    return read(input, path);
  };
}
const sha: Decoder<string> = (input, path = '$') => {
  const value = string(input, path);
  if (!/^[a-f0-9]{64}$/.test(value)) throw new ContractError(path);
  return value;
};
const jobId: Decoder<string> = (input, path = '$') => {
  const value = string(input, path);
  if (!/^[a-f0-9]{32}$/.test(value)) throw new ContractError(path);
  return value;
};
const reviewOnly: Decoder<true> = (input, path = '$') => {
  if (input !== true) throw new ContractError(path);
  return true;
};
const metricShape = object({
  key: oneOf(METRIC_KEYS),
  label: string,
  value: number,
  unit: string,
  kind: oneOf(['descriptor', 'prediction']),
});
export const decodePredictionMetric: Decoder<PredictionMetric> = (input, path = '$') => {
  const metric = metricShape(input, path);
  const spec = METRIC_SPECS.find((value) => value.key === metric.key);
  if (
    !spec ||
    metric.label !== spec.label ||
    metric.unit !== spec.unit ||
    metric.kind !== spec.kind
  )
    throw new ContractError(path);
  if (metric.key !== 'logP' && metric.key !== 'Solubility_AqSolDB' && metric.value < 0)
    throw new ContractError(`${path}.value`);
  if (
    (metric.key === 'hydrogen_bond_donors' || metric.key === 'hydrogen_bond_acceptors') &&
    !Number.isSafeInteger(metric.value)
  )
    throw new ContractError(`${path}.value`);
  return metric;
};
const summaryFields = {
  status: oneOf(['not_run', 'pending', 'running', 'complete', 'failed', 'stale', 'unavailable']),
  source_fingerprint: nullable(sha),
  smiles_sha256: nullable(sha),
  generated_at: nullable(boundedText(100)),
  job_id: nullable(jobId),
  error: nullable(object({ code: string, message: string })),
  review_only: reviewOnly,
};
const summaryShape = object({
  ...summaryFields,
  properties: boundedArray(decodePredictionMetric, METRIC_KEYS.length),
  engine: nullable(object({ name: boundedText(40), version: boundedText(40), model_sha256: sha })),
  warnings: boundedArray(string, 100),
});
const descriptorShape = object({
  ...summaryFields,
  properties: boundedArray(decodePredictionMetric, DESCRIPTOR_KEYS.length),
  engine: nullable(
    object({
      name: oneOf(['RDKit']),
      version: boundedText(40),
      algorithm_sha256: sha,
    }),
  ),
});
function validateSummary<T extends PredictionSummary | DescriptorSummary>(
  summary: T,
  keys: readonly MetricKey[],
  path: string,
): T {
  if (summary.status === 'complete') {
    if (
      summary.properties.length !== keys.length ||
      summary.properties.some((metric, index) => metric.key !== keys[index]) ||
      !summary.source_fingerprint ||
      !summary.smiles_sha256 ||
      !summary.engine ||
      !summary.generated_at
    )
      throw new ContractError(path);
  } else if (summary.properties.length) {
    throw new ContractError(`${path}.properties`);
  }
  return summary;
}
const leadEndpointKeys = new Set([
  'hERG',
  'AMES',
  'DILI',
  'ClinTox',
  'HIA_Hou',
  'Bioavailability_Ma',
  'CYP1A2_Veith',
  'CYP2C9_Veith',
  'CYP2C19_Veith',
  'CYP2D6_Veith',
  'CYP3A4_Veith',
]);
export const decodePredictionSummary: Decoder<PredictionSummary> = (input, path = '$') => {
  const summary = validateSummary(summaryShape(input, path), METRIC_KEYS, path);
  const fields = input as Record<string, unknown>;
  if (!Object.hasOwn(fields, 'endpoints')) return summary;
  const raw = fields.endpoints;
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw))
    throw new ContractError(`${path}.endpoints`);
  const entries = Object.entries(raw);
  if (entries.length > leadEndpointKeys.size || (summary.status !== 'complete' && entries.length))
    throw new ContractError(`${path}.endpoints`);
  const endpoints = Object.fromEntries(
    entries.map(([key, value]) => {
      const scalar = number(value, `${path}.endpoints.${key}`);
      if (!leadEndpointKeys.has(key) || scalar < 0 || scalar > 1)
        throw new ContractError(`${path}.endpoints.${key}`);
      return [key, scalar];
    }),
  );
  return { ...summary, endpoints };
};
export const decodeDescriptorSummary: Decoder<DescriptorSummary> = (input, path = '$') => {
  const summary = validateSummary(descriptorShape(input, path), DESCRIPTOR_KEYS, path);
  if (summary.status === 'complete') {
    if (!summary.job_id || summary.error !== null) throw new ContractError(path);
  } else if (summary.engine !== null || summary.generated_at !== null) {
    throw new ContractError(path);
  }
  if (
    (summary.status === 'pending' || summary.status === 'running') &&
    (!summary.source_fingerprint || !summary.smiles_sha256 || !summary.job_id)
  )
    throw new ContractError(path);
  if (summary.status === 'failed' && summary.error === null)
    throw new ContractError(`${path}.error`);
  if (summary.error && (summary.error.code.length > 100 || summary.error.message.length > 2000))
    throw new ContractError(`${path}.error`);
  return summary;
};
