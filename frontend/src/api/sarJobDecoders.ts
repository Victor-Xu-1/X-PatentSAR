import {
  array,
  boolean,
  count,
  number,
  object,
  oneOf,
  string,
  ContractError,
  positive,
} from './validation';
import { additions, checkPage, hex, nullOr } from './sarDecoders';
import type { Decoder } from './validation';
import type { Pair, SARJob } from './sarTypes';

const job = object({
  id: string,
  dataset_id: string,
  region_id: string,
  metric_id: string,
  status: oneOf(['queued', 'running', 'complete', 'failed', 'cancelled', 'interrupted']),
  processed: count,
  total: count,
  matched: count,
  error_code: nullOr(string),
  error_message: nullOr(string),
  created_at: string,
  started_at: nullOr(string),
  finished_at: nullOr(string),
  input_sha256: hex(64),
  stale: boolean,
});
export const decodeSARJob: Decoder<SARJob> = (v, p = '$') => {
  const result = job(v, p);
  if (result.processed > result.total || result.matched > result.processed)
    throw new ContractError(p);
  return { ...result, ...additions(v, { kind: oneOf(['reference', 'study']) }, p) };
};
export const decodeSARJobs = object({ items: array(decodeSARJob), total: count });
const pair = object({
  reference_id: string,
  molecule_id: string,
  label: string,
  match_status: oneOf(['matched', 'not_matched', 'ambiguous', 'ineligible']),
  reasons: array(string),
  comparison: oneOf(['better', 'worse', 'equal', 'indeterminate', 'missing', 'context_mismatch']),
  reference_values: array(string),
  candidate_values: array(string),
  fold_change: nullOr(number),
  evidence_basis: oneOf(['recorded_context', 'user_confirmed', 'source_declared', 'insufficient']),
});
export const decodePair: Decoder<Pair> = (v, p = '$') => {
  const result = pair(v, p);
  if (
    result.fold_change !== null &&
    (result.fold_change <= 0 ||
      result.match_status !== 'matched' ||
      !['better', 'worse', 'equal'].includes(result.comparison))
  )
    throw new ContractError(`${p}.fold_change`);
  return {
    ...result,
    ...additions(
      v,
      {
        region_id: nullOr(string),
        fragment_id: nullOr(string),
        variable_atom_indices: array(count),
        attachment_mapping: array(array(count)),
      },
      p,
    ),
  };
};
const pairs = object({
  items: array(decodePair),
  total: count,
  page: positive,
  page_size: positive,
  job: decodeSARJob,
});
export const decodePairs = (v: unknown, p = '$') =>
  checkPage(pairs(v, p), p) as ReturnType<typeof pairs>;
