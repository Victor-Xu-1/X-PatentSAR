import { additions, recordOf } from './sarDecoders';
import { array, count, object, oneOf, string, ContractError, type Decoder } from './validation';
import type { StudyReport } from './sarStudyTypes';

const literal =
  <T extends number>(expected: T): Decoder<T> =>
  (value, path = '$') => {
    if (value !== expected) throw new ContractError(path);
    return expected;
  };
const common = object({
  method: oneOf([
    'single-non-ring-bond-v1',
    'single-region-one-two-cut-v2',
    'single-region-one-two-cut-h-v3',
  ]),
  candidate_sites: count,
  candidate_comparisons: count,
  indexed_cuts: count,
  excluded: recordOf(count, 16),
  max_variable_atoms: literal(32),
  max_variable_fraction: literal(0.4),
  min_fixed_atoms: literal(6),
  limitations: array(string),
});

export const decodeStudyDiscovery: Decoder<NonNullable<StudyReport['discovery']>> = (
  value,
  path = '$',
) => {
  const result = {
    ...common(value, path),
    ...additions(
      value,
      {
        examined_boundaries: count,
        indexed_hydrogen_sites: count,
        max_cut_bonds: (raw, p = '$') => {
          if (raw !== 1 && raw !== 2) throw new ContractError(p);
          return raw;
        },
      },
      path,
    ),
  };
  if (
    result.method !== 'single-non-ring-bond-v1' &&
    (result.max_cut_bonds !== 2 ||
      result.examined_boundaries === undefined ||
      result.examined_boundaries > 500000)
  )
    throw new ContractError(path);
  if (
    result.method === 'single-region-one-two-cut-h-v3' &&
    (result.indexed_hydrogen_sites === undefined ||
      result.indexed_hydrogen_sites > result.indexed_cuts)
  )
    throw new ContractError(path);
  if (
    result.method === 'single-non-ring-bond-v1' &&
    result.max_cut_bonds !== undefined &&
    result.max_cut_bonds !== 1
  )
    throw new ContractError(path);
  return result;
};
