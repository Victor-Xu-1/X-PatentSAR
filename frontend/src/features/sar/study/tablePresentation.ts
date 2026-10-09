import type { StudyContext, StudyReport } from '../../../api/sarStudyTypes';
import { METRIC_SPECS } from '../../../api/predictionTypes';
export const studyProperties = METRIC_SPECS;
const countProperties: ReadonlySet<string> = new Set(
  METRIC_SPECS.filter((property) => property.unit === '#').map((property) => property.key),
);
export function selectedContexts(report: StudyReport): StudyContext[] {
  return report.policies.flatMap((policy) =>
    report.contexts.filter((context) => context.id === policy.context_id),
  );
}
export function propertyText(value: number | null | undefined, key?: string) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  // Atom-group counts are integers, not measurements with two decimal places.
  // Never round a fractional imported/manual value into an invented integer.
  if (countProperties.has(key ?? '') && Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}
export interface PageSort {
  column: string;
  direction: 'asc' | 'desc';
}
