import type { StudyContext, StudyReport, StudyRow } from '../../../api/sarStudyTypes';
import { METRIC_SPECS } from '../../../api/predictionTypes';
export const studyProperties = METRIC_SPECS;
export function selectedContexts(report: StudyReport): StudyContext[] {
  return report.policies.flatMap((policy) =>
    report.contexts.filter((context) => context.id === policy.context_id),
  );
}
export function propertyText(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
}
export interface PageSort {
  column: string;
  direction: 'asc' | 'desc';
}
export function sortStudyPage(rows: StudyRow[], sort: PageSort) {
  if (!sort.column) return rows;
  const value = (row: StudyRow): string | number | null => {
    if (sort.column === 'label') return row.label;
    if (sort.column === 'lead') return row.candidate_status;
    if (sort.column.startsWith('property:')) return row.properties[sort.column.slice(9)] ?? null;
    if (sort.column.startsWith('context:'))
      return (row.values[sort.column.slice(8)] ?? []).join(' · ') || null;
    return null;
  };
  const collator = new Intl.Collator('en', { numeric: true });
  return rows.toSorted((a, b) => {
    const left = value(a),
      right = value(b);
    if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
    const comparison =
      typeof left === 'number' && typeof right === 'number'
        ? left - right
        : collator.compare(String(left), String(right));
    return sort.direction === 'asc' ? comparison : -comparison;
  });
}
