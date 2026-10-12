import { object, count, string, oneOf, nullable, ContractError } from './validation';
import { decodeHistoryProjectId, decodeHistoryRevision } from './historyDecoders';
import type { Decoder } from './validation';
import type { TrashPlan, TrashClearReceipt } from './historyTrashTypes';

const counts: Decoder<TrashPlan['counts']> = (value, path = '$') => {
  const result = object({
    project: count,
    job: count,
    export: count,
    environment_operation: count,
  })(value, path);
  if (Object.keys(value as object).length !== 4) throw new ContractError(path);
  return result;
};
export const decodeTrashPlan: Decoder<TrashPlan> = (value, path = '$') => {
  const result = object({
    revision: decodeHistoryRevision,
    total: count,
    counts,
    blocked: count,
    files_total: count,
    bytes_total: count,
    retained_targets: count,
    pending: nullable((v, p) => decodeTrashClearReceipt(v, p)),
  })(value, path);
  if (
    result.total > 25000 ||
    result.blocked > result.total ||
    result.files_total > 25000 ||
    result.bytes_total > 8 * 1024 ** 3 ||
    (result.pending !== null && result.pending.status !== 'cleanup_pending') ||
    Object.values(result.counts).reduce((a, b) => a + b, 0) !== result.total
  )
    throw new ContractError(path + '.trash_counts');
  return result;
};
export const decodeTrashClearReceipt: Decoder<TrashClearReceipt> = (value, path = '$') => {
  const result = object({
    request_id: decodeHistoryProjectId,
    plan_revision: decodeHistoryRevision,
    cleared: count,
    counts,
    started_at: string,
    completed_at: nullable(string),
    files_deleted: count,
    status: oneOf(['complete', 'cleanup_pending'] as const),
    files_total: count,
    files_retained: count,
    bytes_removed: count,
    retained_targets: count,
  })(value, path);
  if (
    !result.cleared ||
    result.cleared > 25000 ||
    result.files_total > 25000 ||
    result.bytes_removed > 8 * 1024 ** 3 ||
    result.files_deleted + result.files_retained > result.files_total ||
    (result.status === 'complete' &&
      result.files_deleted + result.files_retained !== result.files_total) ||
    !result.started_at ||
    result.started_at.length > 80 ||
    (result.completed_at !== null && (!result.completed_at || result.completed_at.length > 80)) ||
    (result.status === 'complete') !== (result.completed_at !== null) ||
    Object.values(result.counts).reduce((a, b) => a + b, 0) !== result.cleared
  )
    throw new ContractError(path + '.trash_clear_counts');
  return result;
};
