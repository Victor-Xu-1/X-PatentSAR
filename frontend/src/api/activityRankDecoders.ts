import type { ActivityStrengthScale } from './types';
import { ContractError, count, nullable, number, object, oneOf, string } from './validation';
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
  const scale = scaleShape(input, path);
  const fields = input as Record<string, unknown>;
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
  if (scale.direction === 'unknown' || scale.eligible === 0) {
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
