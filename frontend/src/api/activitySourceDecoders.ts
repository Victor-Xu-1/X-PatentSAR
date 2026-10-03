import type { ActivityFocusSelection } from './types';
import { array, ContractError, string } from './validation';
import type { Decoder } from './validation';

const sourceKeyPattern = /^[a-f0-9]{64}$/;
export const activitySourceKey: Decoder<string> = (input, path = '$') => {
  const value = string(input, path);
  if (!sourceKeyPattern.test(value)) throw new ContractError(path);
  return value;
};
export function validFocusCompound(value: unknown): value is string {
  if (typeof value !== 'string' || !value.trim()) return false;
  let characters = 0;
  for (const character of value) {
    const code = character.codePointAt(0)!;
    if (++characters > 200 || code < 32 || code === 127) return false;
  }
  return true;
}
export function validActivityFocus(
  value: ActivityFocusSelection | undefined,
): value is ActivityFocusSelection {
  return Boolean(
    value &&
    validFocusCompound(value.compoundId) &&
    typeof value.key === 'string' &&
    sourceKeyPattern.test(value.key),
  );
}
export function decodeActivitySourceKeys(
  input: unknown,
  observations: number,
  path: string,
): string[] {
  if (!Array.isArray(input) || input.length > 2_000 || input.length !== observations)
    throw new ContractError(path);
  return array(activitySourceKey)(input, path);
}
