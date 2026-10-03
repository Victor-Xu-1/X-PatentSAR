import type { Project } from '../../api/types';
export function Metrics({ project }: { project: Project | null }) {
  const coverage = [
    { label: '未关联活性', value: project?.summary.structure_only },
    { label: '结构待定位', value: project?.summary.activity_only },
  ]
    .filter(({ value }) => value != null)
    .map(({ label, value }) => label + ' ' + value)
    .join(' · ');
  const metrics = [
    {
      label: '已提取结构',
      value: project?.summary.structures,
      unit: '条结构记录',
    },
    {
      label: project && project.acceptance.state !== 'accepted' ? '候选活性记录' : '已提取活性',
      value: project?.summary.activity_rows,
      unit: '条数据',
    },
    {
      label: '绑定已确认',
      value: project?.summary.confirmed,
      unit: '条记录',
    },
    {
      label: '绑定待核验',
      value: project?.summary.needs_review,
      unit: '条记录',
    },
    {
      label: '人工已复核',
      value: project?.summary.manually_reviewed,
      unit: '条记录',
      description: '仅计人工已作通过或不通过判定的记录；仍需复核不计完成。',
    },
    {
      label: '人工待复核',
      value: project?.summary.manual_review_pending,
      unit: '条记录',
      description: '包括尚无人工注记及仍需复核的记录；不使用绑定待核验数量。',
    },
  ];
  return (
    <>
      {/* A scrollable statistics region must remain keyboard reachable. */}
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <section className="metrics" aria-label="项目真实统计" tabIndex={0}>
        {metrics.map(({ label, value, unit, description }) => (
          <div className="metric-card" key={label} title={description}>
            <div>
              <span>{label}</span>
              <strong>{value ?? (project ? '未知' : '—')}</strong>
              <small>{!project ? '等待项目数据' : value == null ? '统计未提供' : unit}</small>
            </div>
          </div>
        ))}
      </section>
      {coverage && (
        <small className="muted" aria-label="记录覆盖数量">
          {coverage}
        </small>
      )}
    </>
  );
}
