import type { LeadAssessment } from './leadTypes';
import { leadStatuses } from './leadTypes';
import { ContractError, nullable, number, object, oneOf, positive, string } from './validation';
import type { Decoder } from './validation';

function boundedNumber(max: number): Decoder<number> {
  return (input, path = '$') => {
    const value = number(input, path);
    if (value < 0 || value > max) throw new ContractError(path);
    return value;
  };
}

function boundedText(max: number): Decoder<string> {
  return (input, path = '$') => {
    const value = string(input, path);
    if (value.length > max * 2 || Array.from(value).length > max) throw new ContractError(path);
    return value;
  };
}

const rank: Decoder<number> = (input, path = '$') => {
  const value = positive(input, path);
  if (value > 10) throw new ContractError(path);
  return value;
};
const score = boundedNumber(100);
const fraction = boundedNumber(1);
const components: Decoder<Record<string, number>> = (input, path = '$') => {
  if (input === null || typeof input !== 'object' || Array.isArray(input))
    throw new ContractError(path);
  const keys = ['potency', 'coverage', 'admet', 'physchem', 'evidence', 'diversity'];
  if (
    Object.keys(input).length > keys.length ||
    Object.keys(input).some((key) => !keys.includes(key))
  )
    throw new ContractError(path);
  return Object.fromEntries(
    Object.entries(input).map(([key, value]) => [key, score(value, `${path}.${key}`)]),
  );
};
const notes: Decoder<string[]> = (input, path = '$') => {
  if (!Array.isArray(input) || input.length > 12) throw new ContractError(path);
  return input.map((value, index) => {
    const text = boundedText(300)(value, `${path}[${index}]`);
    if (!text || /[\u0000-\u001f]/.test(text)) throw new ContractError(`${path}[${index}]`);
    return text;
  });
};
const reviewOnly: Decoder<true> = (input, path = '$') => {
  if (input !== true) throw new ContractError(path);
  return true;
};
const shape = {
  status: oneOf(leadStatuses),
  rank: nullable(rank),
  score: nullable(score),
  activity_coverage: fraction,
  components,
  reasons: notes,
  warnings: notes,
  scaffold: nullable(boundedText(2048)),
  nearest_similarity: nullable(fraction),
  policy_version: oneOf(['1']),
  review_only: reviewOnly,
};
const assessment = object(shape);

export const decodeLeadAssessment: Decoder<LeadAssessment> = (input, path = '$') => {
  const value = assessment(input, path);
  // The whole addition may be absent/null on older APIs. A present assessment
  // cannot manufacture missing fields, including nullable scores or rank.
  for (const key of Object.keys(shape)) {
    if (
      !Object.hasOwn(input as object, key) ||
      (input as Record<string, unknown>)[key] === undefined
    )
      throw new ContractError(`${path}.${key}`);
  }
  if (value.status === 'selected' && (value.rank === null || value.score === null))
    throw new ContractError(`${path}.rank`);
  if (value.status !== 'selected' && value.rank !== null) throw new ContractError(`${path}.rank`);
  return value;
};
