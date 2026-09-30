import {
  Activity,
  Clock3,
  FileText,
  FlaskConical,
  FolderOpen,
  Hexagon,
  Settings,
  ShieldCheck,
  Upload,
} from 'lucide-react';
import type { Health, Job, Project } from '../api/types';
import type { Route, View } from '../model/route';
import { acceptanceLabels, jobStatusLabels } from '../model/presentation';

const links = [
  { view: 'projects', label: '项目', icon: FolderOpen },
  { view: 'workspace', label: '结构与活性', icon: FlaskConical },
  { view: 'jobs', label: '任务记录', icon: Clock3 },
  { view: 'settings', label: '运行环境', icon: Settings },
] as const;
export function Sidebar({
  route,
  navigate,
  project,
  job,
  health,
  onUpload,
  disabled,
  inert = false,
}: {
  route: Route;
  navigate: (view: View) => void;
  project: Project | null;
  job: Job | null;
  health: Health | null;
  onUpload: () => void;
  disabled: boolean;
  inert?: boolean;
}) {
  return (
    <aside className="sidebar" id="primary-sidebar" inert={inert}>
      <a className="brand" href="#/" aria-label="X-PatentSAR 工作台">
        <span className="brand-symbol">
          <Hexagon size={31} strokeWidth={2.4} />
          <Activity size={15} />
        </span>
        <span>
          <strong>X-PatentSAR</strong>
          <small>专利结构与活性提取平台</small>
        </span>
      </a>
      <nav aria-label="主导航">
        {links.map(({ view, label, icon: Icon }) => (
          <button
            type="button"
            key={view}
            className={`nav-item${route.view === view ? ' active' : ''}`}
            aria-current={route.view === view ? 'page' : undefined}
            onClick={() => navigate(view)}
          >
            <Icon size={21} />
            {label}
          </button>
        ))}
        <div className="nav-divider" />
        <button type="button" className="nav-item" disabled title="尚未接入 ADMET 预测">
          <ShieldCheck size={21} />
          ADMET<span className="small-tag">未接入</span>
        </button>
        <button type="button" className="nav-item" disabled title="尚未接入智能摘要">
          <FileText size={21} />
          智能摘要<span className="small-tag">未接入</span>
        </button>
      </nav>
      <button className="sidebar-upload" type="button" onClick={onUpload} disabled={disabled}>
        <Upload size={18} />
        上传专利 PDF
      </button>
      <div className="sidebar-project">
        <small>当前项目</small>
        <strong>{project?.title ?? '尚未选择项目'}</strong>
        {project ? (
          <>
            <p>
              {project.summary.structures} 个结构 · {project.summary.activity_rows} 条活性
            </p>
            <span className={`badge ${project.acceptance.state}`}>
              {acceptanceLabels[project.acceptance.state]}
            </span>
            {job && <p className="project-job">最近任务：{jobStatusLabels[job.status]}</p>}
          </>
        ) : (
          <p>导入原始 PDF，开始提取与溯源。</p>
        )}
      </div>
      <footer className="sidebar-footer">
        <span className="status-dot" />
        本地工作台<span>{health ? `v${health.product.version}` : '版本待连接'}</span>
      </footer>
    </aside>
  );
}
