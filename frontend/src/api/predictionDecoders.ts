import { METRIC_KEYS, METRIC_SPECS } from './predictionTypes';
import type { PredictionMetric, PredictionSummary } from './predictionTypes';
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
const summaryShape = object({
  status: oneOf(['not_run', 'pending', 'running', 'complete', 'failed', 'stale', 'unavailable']),
  properties: boundedArray(decodePredictionMetric, METRIC_KEYS.length),
  source_fingerprint: nullable(sha),
  smiles_sha256: nullable(sha),
  engine: nullable(object({ name: boundedText(40), version: boundedText(40), model_sha256: sha })),
  generated_at: nullable(boundedText(100)),
  job_id: nullable(jobId),
  warnings: boundedArray(string, 100),
  error: nullable(object({ code: string, message: string })),
  review_only: reviewOnly,
});
export const decodePredictionSummary: Decoder<PredictionSummary> = (input, path = '$') => {
  const summary = summaryShape(input, path);
  if (summary.status === 'complete') {
    if (
      summary.properties.length !== METRIC_KEYS.length ||
      summary.properties.some((metric, index) => metric.key !== METRIC_KEYS[index]) ||
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
};
