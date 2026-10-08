import { useTranslation, t } from '../../i18n';
import type { LeadAssessment } from '../../api/leadTypes';
import { leadColumnValue } from '../../model/resultColumns';

const statusLabels: Record<LeadAssessment['status'], string> = {
  not_run: '尚未评估',
  stale: '评估已过期，等待更新',
  selected: '研究候选',
  not_selected: '未入选研究候选',
  ineligible: '证据不足，未纳入候选排序',
  unranked: '当前证据无法排序',
};

function assessmentTitle(assessment: LeadAssessment | null | undefined): string {
  if (!assessment) return t('尚未评估 Lead 候选。');
  return [
    [leadColumnValue(assessment), t(statusLabels[assessment.status])].filter(Boolean).join(' · '),
    assessment.score === null
      ? ''
      : t('候选优先级 {score} / 100', { score: assessment.score.toFixed(1) }),
    t('可比活性覆盖 {coverage}%', { coverage: (assessment.activity_coverage * 100).toFixed(0) }),
    assessment.risk_review_required ? t('高模型风险待复核，不代表已验证安全。') : '',
    ...assessment.reasons.map((reason) => t('依据：{reason}', { reason })),
    ...assessment.warnings.map((warning) => t('注意：{warning}', { warning })),
    t('仅供研究优先排序，不代表实验验证或安全、有效性结论。'),
  ]
    .filter(Boolean)
    .join('\n');
}

export function LeadCell({ assessment }: { assessment: LeadAssessment | null | undefined }) {
  const { t } = useTranslation();
  const label = leadColumnValue(assessment);
  const stale = assessment?.status === 'stale';
  return (
    <td
      className="lead-column"
      data-column="lead"
      data-lead-status={assessment?.status ?? 'not_run'}
      title={assessmentTitle(assessment)}
    >
      <span
        className={
          label
            ? `lead-badge${assessment?.risk_review_required ? ' lead-risk-review' : ''}`
            : stale
              ? 'lead-stale'
              : 'lead-placeholder'
        }
      >
        {label || (stale ? t('待更新') : '—')}
      </span>
    </td>
  );
}
