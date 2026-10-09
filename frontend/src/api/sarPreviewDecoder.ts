import { array, object, string, number, ContractError, oneOf } from './validation';
import { decodeRegion, hex, nullOr, recordOf } from './sarDecoders';
import { decodePair, decodeSARJob } from './sarJobDecoders';
import { studyRow } from './sarStudyRowDecoders';
import type { Decoder } from './validation';
import type { StudyPreview } from './sarStudyTypes';
export const decodeStudyPreview: Decoder<StudyPreview> = (value, path = '$') => {
  const result = object({
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
  })(value, path);
  if (
    result.pair.match_status !== 'matched' ||
    result.pair.region_id !== result.region.id ||
    result.pair.reference_id !== result.reference.molecule_id ||
    result.pair.molecule_id !== result.candidate.molecule_id ||
    result.region.molecule_id !== result.reference.molecule_id ||
    result.measurements.length > 8 ||
    new Set(result.measurements.map((m) => m.context_id)).size !== result.measurements.length
  )
    throw new ContractError(path + '.preview_identity');
  return result;
};
