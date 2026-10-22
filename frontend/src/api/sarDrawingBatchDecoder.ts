import { array, nullable, object, oneOf, string, ContractError } from './validation';
import { decodeSARJob } from './sarJobDecoders';
import { decodeStudyDrawing } from './sarStudyDecoders';
import type { StudyDrawing, StudyDrawingKind } from './sarStudyTypes';

export interface DrawingSelection {
  job: string;
  kind: StudyDrawingKind;
  region: string;
}
export interface DrawingEntry {
  identifier: string;
  result: StudyDrawing | null;
  error: { status: 404 | 422; code: string; message: string } | null;
}
const status = (value: unknown, path = '$'): 404 | 422 => {
  if (value !== 404 && value !== 422) throw new ContractError(path);
  return value;
};
const envelope = object({
  job: decodeSARJob,
  kind: oneOf(['molecule', 'scaffold', 'fragment']),
  region_id: string,
  items: array(
    object({
      identifier: string,
      result: nullable(decodeStudyDrawing),
      error: nullable(object({ status, code: string, message: string })),
    }),
  ),
});
export function drawingBatchDecoder(selection: DrawingSelection, keys: string[]) {
  return (value: unknown): DrawingEntry[] => {
    const result = envelope(value);
    if (
      result.job.id !== selection.job ||
      result.job.kind !== 'study' ||
      result.job.status !== 'complete' ||
      result.kind !== selection.kind ||
      result.region_id !== selection.region ||
      result.items.length !== keys.length ||
      keys.length < 1 ||
      keys.length > 32 ||
      new Set(keys).size !== keys.length
    )
      throw new ContractError('$.study_drawings_identity');
    result.items.forEach((item, index) => {
      if (
        item.identifier !== keys[index] ||
        (item.result === null) === (item.error === null) ||
        (item.result && item.result.id !== item.identifier) ||
        (item.error &&
          (!item.error.code || item.error.code.length > 200 || item.error.message.length > 1000))
      )
        throw new ContractError('$.study_drawings_item');
    });
    return result.items;
  };
}
