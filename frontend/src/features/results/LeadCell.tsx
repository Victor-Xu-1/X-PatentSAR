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
  if (!assessment) return '尚未评估 Lead 候选。';
  return [
    [leadColumnValue(assessment), statusLabels[assessment.status]].filter(Boolean).join(' · '),
    assessment.score === null ? '' : `候选优先级 ${assessment.score.toFixed(1)} / 100`,
    `活性覆盖 ${(assessment.activity_coverage * 100).toFixed(0)}%`,
    ...assessment.reasons.map((reason) => `依据：${reason}`),
    ...assessment.warnings.map((warning) => `注意：${warning}`),
    '仅供研究优先排序，不代表实验验证或安全、有效性结论。',
  ]
    .filter(Boolean)
    .join('\n');
}

export function LeadCell({ assessment }: { assessment: LeadAssessment | null | undefined }) {
  const label = leadColumnValue(assessment);
  const stale = assessment?.status === 'stale';
  return (
    <td
      className="lead-column"
      data-column="lead"
      data-lead-status={assessment?.status ?? 'not_run'}
      title={assessmentTitle(assessment)}
    >
      <span className={label ? 'lead-badge' : stale ? 'lead-stale' : 'lead-placeholder'}>
        {label || (stale ? '待更新' : '—')}
      </span>
    </td>
  );
}
