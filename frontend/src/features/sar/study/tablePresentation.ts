import type { StudyContext, StudyReport } from '../../../api/sarStudyTypes';
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
