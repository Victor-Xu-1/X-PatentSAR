import type { CSVMapping, CSVPreview } from '../../api/sarTypes';
import { sarPredictionKeys, sarPropertyKeys } from '../../api/sarStudyTypes';
export type MappingDraft = Omit<CSVMapping, 'token' | 'request_id'>;
export function researchMappingValid(draft: MappingDraft, preview: CSVPreview) {
  const columns = [
    ...Object.values(draft.property_columns ?? {}),
    ...Object.values(draft.prediction_columns ?? {}),
  ];
  return (
    new Set(columns).size === columns.length &&
    columns.every(
      (column) =>
        preview.headers.includes(column) &&
        ![draft.id_column, draft.smiles_column, ...draft.activity_columns].includes(column),
    ) &&
    Object.keys(draft.property_columns ?? {}).every((key) =>
      (sarPropertyKeys as readonly string[]).includes(key),
    ) &&
    Object.keys(draft.prediction_columns ?? {}).every((key) =>
      (sarPredictionKeys as readonly string[]).includes(key),
    )
  );
}
export function initialMapping(preview: CSVPreview): MappingDraft {
  const has = (name: string) => (preview.headers.includes(name) ? name : null);
  const longForm = has('metric') && has('value');
  return {
    title: preview.filename.replace(/\.csv$/i, ''),
    id_column: has('identifier_label') ?? has('compound_id') ?? preview.suggested_id ?? '',
    smiles_column: has('smiles') ?? preview.suggested_smiles ?? '',
    activity_columns: longForm ? ['value'] : [...preview.suggested_activities],
    metric_column: has('metric'),
    unit_column: has('unit'),
    target_column: has('target'),
    assay_column: has('assay'),
    cell_line_column: has('cell_line'),
    duration_column: has('duration'),
  };
}
export function mappingValid(draft: MappingDraft, preview: CSVPreview) {
  const columns = [
    draft.id_column,
    draft.smiles_column,
    ...draft.activity_columns,
    draft.metric_column,
    draft.assay_column,
    draft.target_column,
    draft.unit_column,
    draft.cell_line_column,
    draft.duration_column,
    draft.source_page_column,
    ...Object.values(draft.property_columns ?? {}),
    ...Object.values(draft.prediction_columns ?? {}),
  ].filter((v): v is string => v != null);
  return (
    draft.title.trim().length > 0 &&
    draft.title.length <= 200 &&
    draft.activity_columns.length > 0 &&
    draft.activity_columns.length <= 64 &&
    (!draft.metric_column || draft.activity_columns.length === 1) &&
    researchMappingValid(draft, preview) &&
    new Set(draft.activity_columns).size === draft.activity_columns.length &&
    columns.every((column) => preview.headers.includes(column) && column.length <= 300) &&
    draft.id_column !== draft.smiles_column &&
    !draft.activity_columns.includes(draft.id_column) &&
    !draft.activity_columns.includes(draft.smiles_column) &&
    preview.row_count > 0
  );
}
