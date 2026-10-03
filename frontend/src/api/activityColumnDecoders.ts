import type { Activity, ActivityColumn } from './types';
import { array, ContractError, nullable, object, string } from './validation';
import type { Decoder } from './validation';

export function activityContextKey(
  value: Pick<Activity, 'name' | 'unit' | 'target' | 'assay'>,
): string {
  return JSON.stringify([value.name, value.unit, value.target, value.assay]);
}
const shape = object({
  id: string,
  name: string,
  unit: nullable(string),
  target: nullable(string),
  assay: nullable(string),
});
export const decodeActivityColumns: Decoder<ActivityColumn[]> = (input, path = '$') => {
  if (!Array.isArray(input) || input.length > 1000) throw new ContractError(path);
  const columns = array(shape)(input, path);
  const ids = new Set<string>(),
    contexts = new Set<string>();
  for (const column of columns) {
    const key = activityContextKey(column);
    if (
      !/^[a-f0-9]{64}$/.test(column.id) ||
      !column.name ||
      column.name.length > 1000 ||
      [column.unit, column.target, column.assay].some(
        (value) => value !== null && value.length > 2000,
      ) ||
      ids.has(column.id) ||
      contexts.has(key)
    )
      throw new ContractError(path);
    ids.add(column.id);
    contexts.add(key);
  }
  return columns;
};
