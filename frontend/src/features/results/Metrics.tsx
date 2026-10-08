import { useTranslation } from '../../i18n';
import type { Project } from '../../api/types';
export function Metrics({ project }: { project: Project | null }) {
  const { t } = useTranslation();
  const coverage = [
    { label: t('未关联活性'), value: project?.summary.structure_only },
    { label: t('结构待定位'), value: project?.summary.activity_only },
  ]
    .filter(({ value }) => value != null)
    .map(({ label, value }) => label + ' ' + value)
    .join(' · ');
  const metrics = [
    {
      label: t('已提取结构'),
      value: project?.summary.structures,
      unit: t('条结构记录'),
    },
    {
      label:
        project && project.acceptance.state !== 'accepted' ? t('候选活性记录') : t('已提取活性'),
      value: project?.summary.activity_rows,
      unit: t('条数据'),
    },
    {
      label: t('绑定已确认'),
      value: project?.summary.confirmed,
      unit: t('条记录'),
    },
    {
      label: t('绑定待核验'),
      value: project?.summary.needs_review,
      unit: t('条记录'),
    },
    {
      label: t('人工已复核'),
      value: project?.summary.manually_reviewed,
      unit: t('条记录'),
      description: t('仅计人工已作通过或不通过判定的记录；仍需复核不计完成。'),
    },
    {
      label: t('人工待复核'),
      value: project?.summary.manual_review_pending,
      unit: t('条记录'),
      description: t('包括尚无人工注记及仍需复核的记录；不使用绑定待核验数量。'),
    },
  ];
  return (
    <>
      {/* A scrollable statistics region must remain keyboard reachable. */}
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <section className="metrics" aria-label={t('项目真实统计')} tabIndex={0}>
        {metrics.map(({ label, value, unit, description }) => (
          <div className="metric-card" key={label} title={description}>
            <div>
              <span>{label}</span>
              <strong>{value ?? (project ? t('未知') : '—')}</strong>
              <small>{!project ? t('等待项目数据') : value == null ? t('统计未提供') : unit}</small>
            </div>
          </div>
        ))}
      </section>
      {coverage && (
        <small className="muted" aria-label={t('记录覆盖数量')}>
          {coverage}
        </small>
      )}
    </>
  );
}
