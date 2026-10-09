import type { ActivityStrengthScale } from './types';
import {
  ContractError,
  boolean,
  count,
  nullable,
  number,
  object,
  oneOf,
  string,
} from './validation';
import type { Decoder } from './validation';

const scaleShape = object({
  kind: oneOf(['numeric', 'plus', 'letter', 'unknown']),
  direction: oneOf(['lower', 'higher', 'unknown']),
  rule: string,
  eligible: count,
  excluded: count,
  distinct: count,
  strong_boundary: nullable(number),
  medium_boundary: nullable(number),
});

export const decodeStrengthScale: Decoder<ActivityStrengthScale> = (input, path = '$') => {
  const scale: ActivityStrengthScale = scaleShape(input, path);
  const fields = input as Record<string, unknown>;
  if (Object.hasOwn(fields, 'method')) {
    Object.assign(
      scale,
      object({
        method: oneOf(['tied_terciles', 'tenth_decade']),
        status: oneOf(['ready', 'insufficient', 'ambiguous', 'limit', 'unsupported']),
        boundary_inclusive: boolean,
        population: nullable(count),
        anchor_rank: nullable(count),
        anchor_lower: nullable(number),
        anchor_upper: nullable(number),
        anchor_exponent: nullable(number),
      })(fields, path),
    );
    if (scale.method === 'tenth_decade') {
      if (
        scale.kind !== 'numeric' ||
        (scale.status !== 'unsupported' && scale.direction !== 'lower') ||
        scale.boundary_inclusive ||
        scale.anchor_rank !== 10 ||
        scale.population == null ||
        scale.population > 50000
      )
        throw new ContractError(path);
      if (scale.status === 'ready') {
        if (
          scale.population < 10 ||
          scale.anchor_exponent == null ||
          !Number.isInteger(scale.anchor_exponent) ||
          scale.anchor_exponent < -308 ||
          scale.anchor_exponent > 306 ||
          scale.anchor_lower == null ||
          scale.anchor_upper == null ||
          !(scale.anchor_lower > 0 && scale.anchor_lower <= scale.anchor_upper) ||
          scale.strong_boundary === null ||
          scale.medium_boundary === null ||
          Math.abs(Math.log10(scale.strong_boundary) - scale.anchor_exponent - 1) > 1e-10 ||
          Math.abs(scale.medium_boundary / scale.strong_boundary - 10) > 1e-10
        )
          throw new ContractError(path);
      } else if (
        scale.anchor_lower !== null ||
        scale.anchor_upper !== null ||
        scale.anchor_exponent !== null
      )
        throw new ContractError(path);
    } else if (
      scale.status !== 'ready' ||
      !scale.boundary_inclusive ||
      scale.anchor_rank !== null ||
      scale.anchor_lower !== null ||
      scale.anchor_upper !== null ||
      scale.anchor_exponent !== null ||
      scale.population !== null
    )
      throw new ContractError(path);
  }
  if (!Object.hasOwn(fields, 'strong_boundary') || !Object.hasOwn(fields, 'medium_boundary'))
    throw new ContractError(path);
  const { strong_boundary: strong, medium_boundary: medium } = scale;
  if (
    !scale.rule ||
    scale.rule.length > 64 ||
    scale.distinct > 50000 ||
    scale.distinct > scale.eligible ||
    (scale.eligible > 0 && scale.distinct === 0) ||
    scale.eligible > 50000000 ||
    scale.excluded > 50000000 ||
    (scale.kind === 'unknown' && scale.direction !== 'unknown')
  )
    throw new ContractError(path);
  if (
    scale.direction === 'unknown' ||
    scale.eligible === 0 ||
    (scale.status && scale.status !== 'ready')
  ) {
    if (strong !== null || medium !== null) throw new ContractError(path);
  } else if (
    strong === null ||
    medium === null ||
    (scale.direction === 'lower' && strong > medium) ||
    (scale.direction === 'higher' && strong < medium)
  )
    throw new ContractError(path);
  if (scale.kind === 'plus' || scale.kind === 'letter') {
    const min = scale.kind === 'plus' ? 1 : 0,
      max = scale.kind === 'plus' ? 8 : 25;
    if (
      [strong, medium].some(
        (value) => value !== null && (!Number.isInteger(value) || value < min || value > max),
      )
    )
      throw new ContractError(path);
  }
  return scale;
};

export function decodeActivityRankValues(
  input: unknown,
  length: number,
  path: string,
): (number | null)[] {
  if (!Array.isArray(input) || input.length !== length || input.length > 2000)
    throw new ContractError(path);
  return input.map((value, index) => (value === null ? null : number(value, `${path}[${index}]`)));
}

export function decodeActivityBands(
  input: unknown,
  length: number,
  path: string,
): ('strong' | 'medium' | 'none')[] {
  if (!Array.isArray(input) || input.length !== length || input.length > 2000)
    throw new ContractError(path);
  return input.map((value, index) =>
    oneOf(['strong', 'medium', 'none'])(value, `${path}[${index}]`),
  );
}
