import type { StudyContext, StudyPolicy } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { contextLabel } from './policyDraft';

export function hasStrongRule(policy: StudyPolicy | undefined) {
  if (policy?.strength_method === 'tenth_decade') return policy.strength_scale?.status === 'ready';
  if (policy?.strength_method === 'unclassified') return false;
  return policy?.strong_threshold != null || Boolean(policy?.grade_order.length);
}

/** Display the report's actual rule; never infer patent grade thresholds. */
export function StudyPolicyNote({
  policy,
  context,
  primary = false,
}: {
  policy: StudyPolicy | undefined;
  context: StudyContext | undefined;
  primary?: boolean;
}) {
  const { t } = useTranslation();
  if (!policy || !context || policy.context_id !== context.id) return null;
  if (policy.strength_method === 'tenth_decade') {
    const scale = policy.strength_scale;
    const unit = context.unit ? ' ' + context.unit : '';
    return (
      <p className="sar-policy-note">
        {primary && <strong>{contextLabel(context)}</strong>}
        <span>{t('第十名数量级')}</span>
        <span>
          {scale?.status === 'ready'
            ? t('强 <{strong}；中 {strong}–<{medium}；弱 ≥{medium}', {
                strong: scale.strong_boundary! + unit,
                medium: scale.medium_boundary! + unit,
              })
            : t(
                scale?.status === 'insufficient'
                  ? '不足十个化合物，未分档'
                  : scale?.status === 'ambiguous'
                    ? '第十名数量级不确定，未分档'
                    : '该指标不适用浓度倍数分档',
              )}
        </span>
      </p>
    );
  }
  const relation =
    policy.direction === 'lower'
      ? policy.threshold_inclusive
        ? '≤'
        : '<'
      : policy.threshold_inclusive
        ? '≥'
        : '>';
  return (
    <p className="sar-policy-note">
      {primary && <strong>{contextLabel(context)}</strong>}
      <span>{t('研究规则')}</span>
      {policy.grade_order.length ? (
        <>
          <span>
            {t('分档从强到弱')} {policy.grade_order.join(' → ')}
          </span>
          <span>
            {t('强档')} {policy.grade_order[0]}
          </span>
        </>
      ) : (
        <>
          <span>{t(policy.direction === 'lower' ? '值越低活性越强' : '值越高活性越强')}</span>
          <span>
            {policy.strong_threshold !== null
              ? t('强活性 {rule}', {
                  rule: `${relation} ${policy.strong_threshold}${context.unit ? ' ' + context.unit : ''}`,
                })
              : t('未定义强活性分档')}
          </span>
        </>
      )}
    </p>
  );
}
