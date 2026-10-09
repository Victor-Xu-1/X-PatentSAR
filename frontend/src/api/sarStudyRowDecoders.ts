import {
  array,
  boolean,
  count,
  defaulted,
  number,
  object,
  oneOf,
  string,
  ContractError,
} from './validation';
import { additions, hex, nullOr, recordOf } from './sarDecoders';
import { decodeStrengthScale } from './activityRankDecoders';
import type { Decoder } from './validation';
import type { StudyContext, StudyPolicy, StudyRow } from './sarStudyTypes';
export const studyContext: Decoder<StudyContext> = object({
  id: hex(64),
  metric_id: string,
  name: string,
  unit: nullOr(string),
  context: recordOf(nullOr(string), 8),
  molecule_count: count,
  observation_count: count,
  distinct_value_count: count,
  value_samples: array(string),
});
const policyShape = object({
  context_id: hex(64),
  direction: oneOf(['lower', 'higher']),
  grade_order: defaulted(array(string), []),
  strong_threshold: defaulted(nullOr(number), null),
  threshold_inclusive: defaulted(boolean, true),
});
export const studyPolicy: Decoder<StudyPolicy> = (input, path = '$') => ({
  ...policyShape(input, path),
  ...additions(
    input,
    {
      strength_method: oneOf(['tenth_decade', 'source', 'unclassified']),
      strength_scale: nullOr(decodeStrengthScale),
    },
    path,
  ),
});
export const studyBin = object({
  label: string,
  kind: string,
  observations: count,
  molecules: count,
  strong: defaulted(boolean, false),
});
const fraction: Decoder<number> = (v, p = '$') => {
  const result = number(v, p);
  if (result < 0 || result > 1) throw new ContractError(p);
  return result;
};
const rowShape = object({
  molecule_id: string,
  label: string,
  eligible: boolean,
  scaffold_id: nullOr(string),
  values: recordOf(array(string), 8),
  activity_status: recordOf(string, 8),
  strong: boolean,
  properties: recordOf(nullOr(number), 6),
  property_origins: recordOf(string, 6),
  predictions: defaulted(recordOf(nullOr(number), 11), {}),
  prediction_origin: defaulted(string, 'not_provided'),
  pareto_front: nullOr(count),
  candidate_status: oneOf(['selected', 'not_selected', 'unranked', 'ineligible', 'partial']),
  priority_group: nullOr(count),
  selection_order: nullOr(count),
  coverage: fraction,
  reasons: array(string),
});
export const studyRow: Decoder<StudyRow> = (input, path = '$') => ({
  ...rowShape(input, path),
  ...additions(
    input,
    { activity_bands: recordOf(oneOf(['strong', 'medium', 'weak', 'unclassified']), 8) },
    path,
  ),
});
