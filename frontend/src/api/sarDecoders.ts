import {
  array,
  boolean,
  count,
  number,
  object,
  oneOf,
  positive,
  string,
  ContractError,
} from './validation';
import type { Decoder } from './validation';
import type { CSVPreview, Dataset, Molecule, MoleculeDrawing, Region } from './sarTypes';

export const hex =
  (length: number): Decoder<string> =>
  (value, path = '$') => {
    const result = string(value, path);
    if (!new RegExp(`^[a-f0-9]{${length}}$`).test(result)) throw new ContractError(path);
    return result;
  };
// Null is a fact, not a missing/invalid field silently converted to success.
export const nullOr =
  <T>(decode: Decoder<T>): Decoder<T | null> =>
  (v, p) =>
    v === null ? null : decode(v, p);
export const recordOf =
  <T>(decode: Decoder<T>, limit: number): Decoder<Record<string, T>> =>
  (v, p = '$') => {
    if (!v || typeof v !== 'object' || Array.isArray(v) || Object.keys(v).length > limit)
      throw new ContractError(p);
    return Object.fromEntries(
      Object.entries(v).map(([k, value]) => [k, decode(value, `${p}.${k}`)]),
    );
  };
export function unique(values: readonly (string | number)[], path: string) {
  if (new Set(values).size !== values.length) throw new ContractError(path);
}
export function checkPage<T>(
  value: { items: T[]; total: number; page: number; page_size: number },
  path: string,
) {
  if (value.items.length > value.page_size || value.items.length > value.total)
    throw new ContractError(path);
  return value;
}
const metric = object({
  id: string,
  name: string,
  unit: nullOr(string),
  target: nullOr(string),
  assay: nullOr(string),
});
const observation = object({
  metric_id: string,
  value: string,
  unit: nullOr(string),
  context: recordOf(nullOr(string), 8),
  source_page: nullOr(positive),
  source_row: nullOr(count),
  source_kind: oneOf(['patent', 'imported', 'manual']),
});
export const decodeMolecule: Decoder<Molecule> = object({
  id: string,
  label: string,
  smiles: nullOr(string),
  molfile: nullOr(string),
  graph_sha256: nullOr(hex(64)),
  eligible: boolean,
  issues: array(string),
  observations: array(observation),
  source_compound_id: nullOr(string),
  source_page: nullOr(positive),
});
const dataset = object({
  id: string,
  title: string,
  source_kind: oneOf(['project', 'csv']),
  source_project_id: nullOr(string),
  source_sha256: hex(64),
  revision: positive,
  stale: boolean,
  row_count: count,
  eligible_count: count,
  issue_count: count,
  metrics: array(metric),
  created_at: string,
});
export const decodeDataset: Decoder<Dataset> = (v, p = '$') => {
  const result = dataset(v, p);
  if (result.eligible_count > result.row_count || result.metrics.length > 1000)
    throw new ContractError(p);
  unique(
    result.metrics.map((item) => item.id),
    `${p}.metrics`,
  );
  const input = v as Record<string, unknown>;
  return {
    ...result,
    ...(Object.hasOwn(input, 'input_row_count')
      ? { input_row_count: count(input.input_row_count, `${p}.input_row_count`) }
      : {}),
    ...(Object.hasOwn(input, 'source_document_sha256')
      ? {
          source_document_sha256: nullOr(hex(64))(
            input.source_document_sha256,
            `${p}.source_document_sha256`,
          ),
        }
      : {}),
  };
};
export const decodeDatasets = object({ items: array(decodeDataset), total: count });
const molecules = object({
  items: array(decodeMolecule),
  total: count,
  page: positive,
  page_size: positive,
});
export const decodeMolecules = (v: unknown, p = '$') => checkPage(molecules(v, p), p);
const preview = object({
  token: hex(32),
  filename: string,
  headers: array(string),
  row_count: count,
  samples: array(recordOf(string, 256)),
  suggested_id: nullOr(string),
  suggested_smiles: nullOr(string),
  suggested_activities: array(string),
});
export const decodeCSVPreview: Decoder<CSVPreview> = (v, p = '$') => {
  const result = preview(v, p);
  unique(result.headers, `${p}.headers`);
  if (
    result.headers.length > 256 ||
    result.samples.length > result.row_count ||
    [result.suggested_id, result.suggested_smiles, ...result.suggested_activities].some(
      (field) => field !== null && !result.headers.includes(field),
    ) ||
    result.samples.some((row) => Object.keys(row).some((key) => !result.headers.includes(key)))
  )
    throw new ContractError(p);
  return result;
};
const coordinate: Decoder<number> = (v, p) => {
  const result = number(v, p);
  if (result < 0 || result > 1) throw new ContractError(p ?? '$');
  return result;
};
const drawing = object({
  molecule: decodeMolecule,
  svg: string,
  atoms: array(object({ index: count, element: string, x: coordinate, y: coordinate })),
});
export const decodeDrawing: Decoder<MoleculeDrawing> = (v, p = '$') => {
  const result = drawing(v, p);
  if (result.atoms.length > 512 || result.svg.length > 1024 * 1024) throw new ContractError(p);
  unique(
    result.atoms.map((atom) => atom.index),
    `${p}.atoms`,
  );
  return result;
};
const region = object({
  id: hex(32),
  dataset_id: string,
  molecule_id: string,
  dataset_revision: positive,
  graph_sha256: hex(64),
  atom_indices: array(count),
  attachment_count: count,
  created_at: string,
});
export const decodeRegion: Decoder<Region> = (v, p = '$') => {
  const result = region(v, p);
  if (!result.atom_indices.length || result.atom_indices.length > 512) throw new ContractError(p);
  unique(result.atom_indices, `${p}.atom_indices`);
  return result;
};
