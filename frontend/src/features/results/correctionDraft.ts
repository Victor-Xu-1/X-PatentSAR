import type { Activity, ActivityColumn, Compound } from '../../api/types';
import type { EditableFields } from '../../api/correctionTypes';
import type { PropertyOverrides } from '../../api/manualPropertyTypes';
import { METRIC_SPECS } from '../../api/predictionTypes';
import type { MetricKey } from '../../api/predictionTypes';
import { decodeEditableFields } from '../../api/correctionDecoders';
import { activityContextKey } from '../../api/activityColumnDecoders';
import { effectiveProperty } from '../../model/propertyValues';
import { compoundLabel } from '../../model/compoundLabel';

export interface ActivityDraft {
  source: Activity;
  value: string;
  added: boolean;
}
export interface PropertyDraft {
  value: string;
  overridden: boolean;
  touched: boolean;
}
export interface StructureChange {
  smiles: string;
  molfile: string | null;
  graphKey: string;
  graphChanged: boolean;
}
export interface CorrectionDraft {
  displayId: string;
  identifierOrigin?: { canonical: string; label: string };
  smiles: string;
  molfile: string | null;
  graphKey: string | null;
  properties: Record<MetricKey, PropertyDraft>;
  activities: ActivityDraft[];
}
export function activityDraft(activity: Activity, added = false): ActivityDraft {
  return {
    source: { ...activity },
    value: activity.value === null ? '' : String(activity.value),
    added,
  };
}
export function correctionDraft(
  fields: EditableFields,
  compound?: Compound,
  columns: ActivityColumn[] = [],
): CorrectionDraft {
  const activities = fields.activities.map((activity) => activityDraft(activity));
  const present = new Set(fields.activities.map(activityContextKey));
  for (const column of columns) {
    const key = activityContextKey(column);
    if (!present.has(key)) {
      activities.push(
        activityDraft(
          {
            name: column.name,
            unit: column.unit,
            target: column.target,
            assay: column.assay,
            value: null,
            page: null,
          },
          true,
        ),
      );
      present.add(key);
    }
  }
  const overrides = fields.property_overrides ?? {};
  const properties = Object.fromEntries(
    METRIC_SPECS.map(({ key }) => {
      const overridden = Object.hasOwn(overrides, key);
      const value = overridden
        ? overrides[key]
        : compound
          ? effectiveProperty(compound, key).value
          : null;
      return [
        key,
        {
          value:
            value == null
              ? ''
              : overridden || Number.isInteger(value)
                ? String(value)
                : value.toFixed(2),
          overridden,
          touched: false,
        },
      ];
    }),
  ) as Record<MetricKey, PropertyDraft>;
  return {
    displayId:
      compound && fields.display_id === compound.display_id
        ? compoundLabel(compound)
        : fields.display_id,
    ...(compound && fields.display_id === compound.display_id
      ? { identifierOrigin: { canonical: fields.display_id, label: compoundLabel(compound) } }
      : {}),
    smiles: fields.smiles ?? '',
    molfile: fields.structure_molfile ?? null,
    graphKey: null,
    properties,
    activities,
  };
}
export function changeStructureDraft(
  draft: CorrectionDraft,
  change: StructureChange,
): CorrectionDraft {
  // Coordinates are editable without clearing values. Only a different molecular
  // graph invalidates values entered for the previous drawing.
  const graphMoved =
    draft.graphKey === null ? change.graphChanged : change.graphKey !== draft.graphKey;
  return {
    ...draft,
    smiles: change.smiles,
    molfile: change.molfile,
    graphKey: change.graphKey,
    properties: graphMoved
      ? (Object.fromEntries(
          METRIC_SPECS.map(({ key }) => [key, { value: '', overridden: false, touched: false }]),
        ) as Record<MetricKey, PropertyDraft>)
      : draft.properties,
  };
}
const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
export function activityValue(item: ActivityDraft): Activity['value'] {
  const original = item.source.value;
  if (item.value === (original === null ? '' : String(original))) return original;
  const text = item.value.trim();
  if (!text) return null;
  if (!decimal.test(text)) return text; // grades, ranges and censored values stay text
  const value = Number(text);
  if (!Number.isFinite(value)) throw new Error('活性数值必须是有限数字。');
  return value;
}
export function draftFields(draft: CorrectionDraft): EditableFields {
  const overrides: PropertyOverrides = {};
  for (const { key, label } of METRIC_SPECS) {
    const item = draft.properties[key];
    if (!item.overridden && !item.touched) continue;
    const text = item.value.trim();
    if (text && (!decimal.test(text) || !Number.isFinite(Number(text))))
      throw new Error(`${label} 必须是有限数字，或留空。`);
    overrides[key] = text ? Number(text) : null;
  }
  const smiles = draft.smiles.trim() || null;
  return decodeEditableFields({
    display_id:
      draft.identifierOrigin && draft.displayId.trim() === draft.identifierOrigin.label
        ? draft.identifierOrigin.canonical
        : draft.displayId.trim(),
    smiles,
    structure_molfile: draft.molfile,
    property_overrides: overrides,
    property_basis_smiles: Object.keys(overrides).length ? smiles : null,
    activities: draft.activities
      .filter((item) => !item.added || item.value.trim())
      .map((item) => ({ ...item.source, value: activityValue(item) })),
  });
}
