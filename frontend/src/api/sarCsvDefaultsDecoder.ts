/** Validate server-owned mapping facts; never infer roles from client values. */
import { additions, recordOf, unique } from './sarDecoders';
import { array, object, string, ContractError } from './validation';
import type { CSVPreview } from './sarTypes';
import { sarPredictionKeys, sarPropertyKeys } from './sarStudyTypes';

const columns = [
  'metric_column',
  'unit_column',
  'target_column',
  'assay_column',
  'cell_line_column',
  'duration_column',
  'source_page_column',
];
export function csvMappingDefaults(value: unknown, preview: CSVPreview, path: string) {
  const extra = additions(
    value,
    {
      mapping_defaults: object({
        columns: recordOf(string, 7),
        property_columns: recordOf(string, 6),
        prediction_columns: recordOf(string, 11),
        ambiguous_roles: array(string),
      }),
    },
    path,
  );
  if (!extra.mapping_defaults) return extra;
  const defaults = extra.mapping_defaults;
  const hinted = [
    ...Object.values(defaults.columns),
    ...Object.values(defaults.property_columns),
    ...Object.values(defaults.prediction_columns),
  ];
  if (
    Object.keys(defaults.columns).some((key) => !columns.includes(key)) ||
    Object.keys(defaults.property_columns).some(
      (key) => !(sarPropertyKeys as readonly string[]).includes(key),
    ) ||
    Object.keys(defaults.prediction_columns).some(
      (key) => !(sarPredictionKeys as readonly string[]).includes(key),
    ) ||
    defaults.ambiguous_roles.length > 32 ||
    defaults.ambiguous_roles.some((role) => role.length > 64) ||
    hinted.some((column) => !preview.headers.includes(column) || column.length > 300) ||
    hinted.some((column) =>
      [preview.suggested_id, preview.suggested_smiles, ...preview.suggested_activities].includes(
        column,
      ),
    )
  )
    throw new ContractError(path + '.mapping_defaults');
  unique(hinted, path + '.mapping_defaults');
  return extra;
}
