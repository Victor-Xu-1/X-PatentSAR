import { array, object, string, number, ContractError, oneOf } from './validation';
import { additions, decodeRegion, hex, nullOr, recordOf } from './sarDecoders';
import { decodePair, decodeSARJob } from './sarJobDecoders';
import { studyRow } from './sarStudyRowDecoders';
import type { Decoder } from './validation';
import type { StudyPreview } from './sarStudyTypes';
import { decodePreviewDrawings } from './sarPreviewDrawingDecoder';
export const decodeStudyPreview: Decoder<StudyPreview> = (value, path = '$') => {
  const result = {
    ...object({
      job: decodeSARJob,
      region: decodeRegion,
      reference: studyRow,
      candidate: studyRow,
      pair: decodePair,
      measurements: array(
        object({
          context_id: hex(64),
          reference_values: array(string),
          candidate_values: array(string),
          comparison: oneOf([
            'better',
            'worse',
            'equal',
            'indeterminate',
            'missing',
            'context_mismatch',
          ]),
          evidence_basis: oneOf([
            'recorded_context',
            'source_declared',
            'user_confirmed',
            'insufficient',
          ]),
          raw_difference: nullOr(number),
        }),
      ),
      property_differences: recordOf(nullOr(number), 6),
    })(value, path),
    ...additions(
      value,
      {
        drawings: nullOr(decodePreviewDrawings),
        property_statuses: recordOf(
          oneOf([
            'comparable',
            'missing',
            'origin_unknown',
            'origin_mismatch',
            'not_representable',
          ]),
          6,
        ),
        recorded_measurements: array(
          object({
            context_id: hex(64),
            reference_values: array(string),
            candidate_values: array(string),
          }),
        ),
      },
      path,
    ),
  };
  const recorded = result.recorded_measurements ?? [];
  const statuses = result.property_statuses ?? {};
  if (
    Object.keys(statuses).length &&
    (Object.keys(statuses).length !== Object.keys(result.property_differences).length ||
      Object.entries(statuses).some(
        ([key, status]) =>
          !(key in result.property_differences) ||
          (status === 'comparable') !== (result.property_differences[key] != null),
      ))
  )
    throw new ContractError(path + '.property_comparison_status');
  const contexts = [...result.measurements, ...recorded].map((item) => item.context_id);
  if (
    result.pair.match_status !== 'matched' ||
    result.pair.region_id !== result.region.id ||
    result.pair.reference_id !== result.reference.molecule_id ||
    result.pair.molecule_id !== result.candidate.molecule_id ||
    result.region.molecule_id !== result.reference.molecule_id ||
    result.measurements.length > 8 ||
    recorded.length > 1000 ||
    new Set(contexts).size !== contexts.length ||
    (result.drawings &&
      (result.drawings.reference.id !== result.reference.molecule_id ||
        result.drawings.candidate.id !== result.candidate.molecule_id))
  )
    throw new ContractError(path + '.preview_identity');
  return result;
};
