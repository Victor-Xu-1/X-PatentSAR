import { array, object, positive, string, ContractError } from './validation';
import { hex, recordOf, unique } from './sarDecoders';
import type { Decoder } from './validation';
import type { ConditionDeclaration } from './sarStudyTypes';

const shape = object({
  context_id: hex(64),
  fields: recordOf(string, 4),
  source_document_sha256: hex(64),
  source_pages: array(positive),
  note: string,
});
export const decodeConditionDeclaration: Decoder<ConditionDeclaration> = (value, path = '$') => {
  const result = shape(value, path);
  unique(result.source_pages, path + '.source_pages');
  if (
    !Object.keys(result.fields).length ||
    Object.entries(result.fields).some(
      ([key, field]) =>
        !['target', 'assay', 'cell_line', 'duration'].includes(key) ||
        !field.trim() ||
        field.length > 1000,
    ) ||
    !result.source_pages.length ||
    result.source_pages.length > 12 ||
    result.source_pages.some((page) => page > 20000) ||
    !result.note.trim() ||
    result.note.length > 2000
  )
    throw new ContractError(path);
  return result;
};
