import type { StudyPolicy } from '../../../api/sarStudyTypes';
import { gradeOrder } from '../presentation';
export interface PolicyDraft {
  direction: '' | 'lower' | 'higher';
  grades: string;
}
export const emptyPolicy = (): PolicyDraft => ({
  direction: '',
  grades: '',
});
export function policyFromDraft(id: string, draft: PolicyDraft): StudyPolicy | null {
  const grades = gradeOrder(draft.grades);
  if (!draft.direction || !grades.valid) return null;
  return {
    context_id: id,
    direction: draft.direction,
    grade_order: grades.values,
    strong_threshold: null,
    threshold_inclusive: false,
    strength_method: grades.values.length ? 'source' : 'tenth_decade',
  };
}
export const contextLabel = (context: { name: string; unit: string | null }) =>
  context.unit &&
  !context.name.endsWith('(' + context.unit + ')') &&
  !context.name.endsWith(' ' + context.unit)
    ? context.name + ' · ' + context.unit
    : context.name;
