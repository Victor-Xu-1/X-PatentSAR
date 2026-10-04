import type { Compound } from '../api/types';
import type { ResultColumn } from './resultColumns';
import { activityColumnObservations } from './activityColumns';
import type { TableActivityColumn } from './activityColumns';
import { METRIC_SPECS } from '../api/predictionTypes';
import { effectiveProperty } from './propertyValues';

// TSV is plain text: neutralize spreadsheet formula prefixes only in the copy,
// and remove embedded row/column separators so each original row stays one row.
export function safeTsvCell(value: string | number | null | undefined): string {
  // Typed finite numbers cannot contain spreadsheet code. Preserve negative
  // LogP/LogS as numeric TSV tokens; the same-looking strings remain escaped.
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  const text = String(value ?? '').replace(/[\p{Cc}\p{Zl}\p{Zp}]+/gu, ' ');
  return /^[\s\uFEFF]*[=+\-@]/u.test(text) ? `'${text}` : text;
}

export function tableCopyText(
  rows: readonly Compound[],
  headers: readonly ResultColumn[],
  activities: TableActivityColumn[],
): string {
  const columns = headers.filter((header) => header.id !== 'select');
  const heading = columns
    .map((header) => safeTsvCell([header.label, header.context].filter(Boolean).join(' · ')))
    .join('\t');
  const lines = rows.map((row) => {
    const observations = activityColumnObservations(row, activities);
    const values = new Map(
      activities.map((column, index) => [
        `activity:${column.id}`,
        observations[index]!.map(({ activity }) => String(activity.value ?? '')).join(' | '),
      ]),
    );
    return columns
      .map((column) => {
        if (column.id === 'compound') return safeTsvCell(row.display_id);
        if (column.id === 'structure')
          return safeTsvCell(
            row.smiles ?? (row.structure_image_url ? '原文结构裁图（无 SMILES）' : ''),
          );
        if (column.id.startsWith('activity:')) return safeTsvCell(values.get(column.id));
        if (column.id.startsWith('property:')) {
          const spec = METRIC_SPECS.find((metric) => `property:${metric.key}` === column.id);
          return safeTsvCell(spec ? effectiveProperty(row, spec.key).value : null);
        }
        if (column.id === 'source') return safeTsvCell(row.source.page);
        if (column.id === 'edit')
          return safeTsvCell(
            row.correction?.stale
              ? 'stale'
              : row.correction?.has_changes
                ? 'corrected'
                : 'original',
          );
        return '';
      })
      .join('\t');
  });
  return [heading, ...lines].join('\n');
}
