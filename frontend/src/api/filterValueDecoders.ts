import { activityBands } from './types';
import type { FilterValues } from './types';
import { array, ContractError, count, object, oneOf, positive, string } from './validation';
import type { Decoder } from './validation';

const shape = object({
  column: string,
  kind: oneOf(['number', 'text', 'presence']),
  items: array(object({ value: string, count: positive })),
  total: count,
  page: positive,
  page_size: positive,
  empty_count: count,
  matching_rows: count,
});
const bands = array(object({ value: oneOf(activityBands), count }));

export const decodeFilterValues: Decoder<FilterValues> = (input, path = '$') => {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ContractError(path);
  const fields = input as Record<string, unknown>;
  if (!Array.isArray(fields.items) || fields.items.length > 200)
    throw new ContractError(`${path}.items`);
  const result: FilterValues = shape(input, path);
  if (
    !result.column ||
    Array.from(result.column).length > 100 ||
    result.total > 25000 ||
    result.page > 25000 ||
    result.page_size > 200 ||
    result.matching_rows > 25000 ||
    result.empty_count > result.matching_rows ||
    result.items.length > result.page_size ||
    result.items.length > result.total ||
    new Set(result.items.map((item) => item.value)).size !== result.items.length ||
    result.items.some(
      (item) =>
        !item.value.trim() ||
        Array.from(item.value).length > 1000 ||
        item.count > result.matching_rows,
    ) ||
    (result.kind === 'presence' && (result.items.length !== 0 || result.total !== 0)) ||
    (result.column === 'structure' && result.kind !== 'presence') ||
    (result.kind === 'presence' && result.column !== 'structure') ||
    ((result.column === 'source' || result.column.startsWith('property:')) &&
      result.kind !== 'number')
  )
    throw new ContractError(path);
  if (fields.bands != null) {
    if (!Array.isArray(fields.bands) || fields.bands.length > 3)
      throw new ContractError(`${path}.bands`);
    result.bands = bands(fields.bands, `${path}.bands`);
    if (
      new Set(result.bands.map((item) => item.value)).size !== result.bands.length ||
      result.bands.some((item) => item.count > result.matching_rows)
    )
      throw new ContractError(`${path}.bands`);
  }
  return result;
};
