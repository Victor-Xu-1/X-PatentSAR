import { additions, recordOf } from './sarDecoders';
import {
  array,
  boolean,
  count,
  object,
  oneOf,
  string,
  ContractError,
  type Decoder,
} from './validation';
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
    'single-region-one-to-three-cut-h-v4',
    'single-region-three-port-aromatic-h-v5',
    'single-region-three-port-multiple-h-v6',
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
        redundant_proved_sites: count,
        aromatic_boundaries: boolean,
        multiple_bond_boundaries: boolean,
        max_cut_bonds: (raw, p = '$') => {
          if (raw !== 1 && raw !== 2 && raw !== 3) throw new ContractError(p);
          return raw;
        },
      },
      path,
    ),
  };
  if (
    result.method !== 'single-non-ring-bond-v1' &&
    (result.max_cut_bonds !==
      (['single-region-one-to-three-cut-h-v4', 'single-region-three-port-aromatic-h-v5', 'single-region-three-port-multiple-h-v6'].includes(
        result.method,
      )
        ? 3
        : 2) ||
      result.examined_boundaries === undefined ||
      result.examined_boundaries > 500000)
  )
    throw new ContractError(path);
  if (
    (result.method === 'single-region-one-two-cut-h-v3' ||
      result.method === 'single-region-one-to-three-cut-h-v4' ||
      result.method === 'single-region-three-port-aromatic-h-v5' ||
      result.method === 'single-region-three-port-multiple-h-v6') &&
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
  if (
    ['single-region-three-port-aromatic-h-v5', 'single-region-three-port-multiple-h-v6'].includes(result.method)
      ? result.aromatic_boundaries !== true
      : result.aromatic_boundaries === true
  )
    throw new ContractError(path);
  if (
    result.method === 'single-region-three-port-multiple-h-v6'
      ? result.multiple_bond_boundaries !== true
      : result.multiple_bond_boundaries === true
  )
    throw new ContractError(path);
  return result;
};
