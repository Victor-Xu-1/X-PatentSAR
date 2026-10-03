import type { Activity, ActivityColumn } from './types';
import { array, boolean, ContractError, count, nullable, object, string } from './validation';
import type { Decoder } from './validation';
import { decodeStrengthScale } from './activityRankDecoders';

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
function choices(value: unknown, path: string): { value: string; count: number }[] {
  if (!Array.isArray(value) || value.length > 200) throw new ContractError(path);
  const parsed = array(object({ value: string, count }))(value, path);
  if (
    new Set(parsed.map((item) => item.value)).size !== parsed.length ||
    parsed.some((item) => item.value.length > 1000 || item.count > 50000000)
  )
    throw new ContractError(path);
  return parsed;
}
export const decodeActivityColumns: Decoder<ActivityColumn[]> = (input, path = '$') => {
  if (!Array.isArray(input) || input.length > 1000) throw new ContractError(path);
  const columns = array(shape)(input, path).map((column, index) => {
    const fields = input[index] as Record<string, unknown>;
    return {
      ...column,
      ...(Object.hasOwn(fields, 'filter_values')
        ? { filter_values: choices(fields.filter_values, `${path}[${index}].filter_values`) }
        : {}),
      ...(Object.hasOwn(fields, 'filter_values_truncated')
        ? {
            filter_values_truncated: boolean(
              fields.filter_values_truncated,
              `${path}[${index}].filter_values_truncated`,
            ),
          }
        : {}),
      ...(Object.hasOwn(fields, 'strength_scale')
        ? {
            strength_scale: nullable(decodeStrengthScale)(
              fields.strength_scale,
              `${path}[${index}].strength_scale`,
            ),
          }
        : {}),
    };
  });
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
