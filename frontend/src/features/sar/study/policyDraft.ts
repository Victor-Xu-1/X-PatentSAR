import type { StudyPolicy } from '../../../api/sarStudyTypes';
import { gradeOrder } from '../presentation';
export interface PolicyDraft {
  direction: '' | 'lower' | 'higher';
  grades: string;
  threshold: string;
  inclusive: boolean;
}
export const emptyPolicy = (): PolicyDraft => ({
  direction: '',
  grades: '',
  threshold: '',
  inclusive: true,
});
export function policyFromDraft(id: string, draft: PolicyDraft): StudyPolicy | null {
  const grades = gradeOrder(draft.grades);
  const raw = draft.threshold.trim();
  if (
    !draft.direction ||
    !grades.valid ||
    (raw && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw))
  )
    return null;
  const value = raw ? Number(raw) : null;
  if (raw && grades.values.length) return null;
  if (value !== null && !Number.isFinite(value)) return null;
  return {
    context_id: id,
    direction: draft.direction,
    grade_order: grades.values,
    strong_threshold: value,
    threshold_inclusive: draft.inclusive,
  };
}
export const contextLabel = (context: { name: string; unit: string | null }) =>
  [context.name, context.unit].filter((v) => v !== null).join(' · ');
