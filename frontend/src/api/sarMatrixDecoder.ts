import { array, ContractError, object } from './validation';
import { decodeStudyDrawing } from './sarStudyDecoders';
import { decodeStudyPreview } from './sarPreviewDecoder';
import type { Decoder } from './validation';
import type { StudyMatrix } from './sarStudyTypes';

export const decodeStudyMatrix: Decoder<StudyMatrix> = (value, path = '$') => {
  const result = object({
    reference_drawing: decodeStudyDrawing,
    previews: array(decodeStudyPreview),
  })(value, path);
  const first = result.previews[0];
  if (
    !first ||
    result.previews.length > 6 ||
    result.reference_drawing.id !== first.reference.molecule_id ||
    !result.reference_drawing.svg ||
    new Set(result.previews.map((item) => item.candidate.molecule_id)).size !==
      result.previews.length ||
    result.previews.some(
      (item) =>
        !item.drawings ||
        JSON.stringify(item.job) !== JSON.stringify(first.job) ||
        JSON.stringify(item.reference) !== JSON.stringify(first.reference),
    )
  )
    throw new ContractError(path + '.matrix_identity');
  return result;
};
