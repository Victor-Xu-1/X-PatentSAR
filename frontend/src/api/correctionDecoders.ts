import type { CorrectionDocument, EditableFields } from './correctionTypes';
import {
  array,
  boolean,
  ContractError,
  count,
  nullable,
  object,
  positive,
  scalar,
  string,
} from './validation';

const boundedText =
  (limit: number, required = false) =>
  (value: unknown, path = '$') => {
    const text = string(value, path);
    if (text.length > limit || (required && !text.trim()) || /\p{C}/u.test(text))
      throw new ContractError(path);
    return text;
  };
const fingerprint = (value: unknown, path = '$') => {
  const text = string(value, path);
  if (!/^[a-f0-9]{64}$/.test(text)) throw new ContractError(path);
  return text;
};
const measurement = object({
  name: boundedText(300, true),
  value: nullable(scalar),
  unit: nullable(boundedText(100)),
  target: nullable(boundedText(300)),
  assay: nullable(boundedText(1000)),
  page: nullable(positive),
});
export const decodeEditableFields = (value: unknown, path = '$'): EditableFields => {
  const fields = object({
    display_id: boundedText(200, true),
    smiles: nullable(boundedText(2048)),
    activities: array(measurement),
  })(value, path);
  if (fields.activities.length > 100) throw new ContractError(`${path}.activities`);
  for (const [index, activity] of fields.activities.entries()) {
    if (activity.page !== null && activity.page > 20000)
      throw new ContractError(`${path}.activities[${index}].page`);
    if (typeof activity.value === 'string' && activity.value.length > 1000)
      throw new ContractError(`${path}.activities[${index}].value`);
  }
  return fields;
};
export const decodeCorrection = (value: unknown, path = '$'): CorrectionDocument => {
  const document = object({
    source_fingerprint: fingerprint,
    revision: count,
    basis_fingerprint: nullable(fingerprint),
    stale: boolean,
    has_changes: boolean,
    original: decodeEditableFields,
    values: decodeEditableFields,
    updated_at: nullable(string),
  })(value, path);
  if (document.revision > 2147483646) throw new ContractError(`${path}.revision`);
  if (document.revision === 0 && (document.has_changes || document.stale))
    throw new ContractError(path);
  return document;
};
