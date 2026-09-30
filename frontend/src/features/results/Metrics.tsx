import { FileCheck2, FlaskConical, Network, ShieldCheck } from 'lucide-react';
import type { Project } from '../../api/types';
export function Metrics({ project }: { project: Project | null }) {
  const metrics = [
    {
      label: '已识别结构',
      value: project?.summary.structures,
      icon: Network,
      unit: '个结构',
    },
    {
      label: '已提取活性',
      value: project?.summary.activity_rows,
      icon: FlaskConical,
      unit: '条数据',
    },
    {
      label: '证据已确认',
      value: project?.summary.confirmed,
      icon: ShieldCheck,
      unit: '个化合物',
    },
    {
      label: '待人工复核',
      value: project?.summary.needs_review,
      icon: FileCheck2,
      unit: '个化合物',
    },
  ];
  return (
    <div className="metrics" aria-label="项目真实统计">
      {metrics.map(({ label, value, icon: Icon, unit }) => (
        <div className="metric-card" key={label}>
          <span className="metric-icon">
            <Icon size={21} strokeWidth={1.65} />
          </span>
          <div>
            <span>{label}</span>
            <strong>{value ?? '—'}</strong>
            <small>{value === undefined ? '等待项目数据' : unit}</small>
          </div>
        </div>
      ))}
    </div>
  );
}
