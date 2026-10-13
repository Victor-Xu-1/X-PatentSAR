import { array, count, object, positive, string, ContractError } from './validation';
import { checkPage, nullOr } from './sarDecoders';
import { decodeSARJob } from './sarJobDecoders';
import type { JobState, SARJob } from './sarTypes';

export interface SARHistoryItem {
  job: SARJob;
  dataset_title: string;
  title: string | null;
}
export interface SARHistoryPage {
  items: SARHistoryItem[];
  total: number;
  page: number;
  page_size: number;
  active_count: number;
}
export interface SARHistoryQuery {
  page: number;
  datasetId: string;
  status: JobState | '';
}
const decode = object({
  items: array(object({ job: decodeSARJob, dataset_title: string, title: nullOr(string) })),
  total: count,
  page: positive,
  page_size: positive,
  active_count: count,
});
export function decodeSARHistory(value: unknown, path = '$'): SARHistoryPage {
  const result = decode(value, path);
  checkPage(result, path);
  if (
    result.page_size > 100 ||
    result.page > 2048 ||
    result.active_count > result.total ||
    new Set(result.items.map((item) => item.job.id)).size !== result.items.length
  )
    throw new ContractError(path + '.sar_history');
  return result;
}
