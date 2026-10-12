import { ContractError, object, oneOf, positive } from './validation';
import { nullOr } from './sarDecoders';
import { decodeStudyDrawing } from './sarStudyDecoders';
import type { Decoder } from './validation';
import type { PreviewDrawingPair } from './sarStudyTypes';

export const decodePreviewDrawings: Decoder<PreviewDrawingPair> = (value, path = '$') => {
  const result = object({
    reference: decodeStudyDrawing,
    candidate: decodeStudyDrawing,
    layout: oneOf(['fixed_background', 'independent']),
    equivalent_mappings: positive,
    reason: nullOr(oneOf(['depiction_failed'])),
  })(value, path);
  if (
    result.equivalent_mappings > 64 ||
    (result.layout === 'fixed_background') !== (result.reason === null) ||
    !result.reference.svg ||
    !result.candidate.svg ||
    !result.reference.id ||
    !result.candidate.id ||
    result.reference.id.length > 200 ||
    result.candidate.id.length > 200
  )
    throw new ContractError(path + '.drawing_layout');
  return result;
};
