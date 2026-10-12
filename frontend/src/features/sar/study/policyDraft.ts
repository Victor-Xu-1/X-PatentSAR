import type { IndicatorDefault, StudyPolicy } from '../../../api/sarStudyTypes';
import { gradeOrder } from '../presentation';
export interface PolicyDraft {
  direction: '' | 'lower' | 'higher';
  grades: string;
}
export const emptyPolicy = (): PolicyDraft => ({
  direction: '',
  grades: '',
});
export function resolvedDirection(
  draft: PolicyDraft['direction'],
  hint?: IndicatorDefault,
): PolicyDraft['direction'] {
  return hint && hint.direction !== 'unknown' ? hint.direction : draft;
}
export function policyFromDraft(
  id: string,
  draft: PolicyDraft,
  hint?: IndicatorDefault,
): StudyPolicy | null {
  const grades = gradeOrder(draft.grades);
  const direction = resolvedDirection(draft.direction, hint);
  if (!direction || !grades.valid) return null;
  return {
    context_id: id,
    direction,
    grade_order: grades.values,
    strong_threshold: null,
    threshold_inclusive: false,
    strength_method: grades.values.length ? 'source' : 'tenth_decade',
  };
}
