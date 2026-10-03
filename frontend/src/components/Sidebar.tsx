import {
  Clock3,
  FileText,
  FlaskConical,
  FolderOpen,
  Settings,
  ShieldCheck,
  SquarePlus,
} from 'lucide-react';
import type { Health, Job, Project } from '../api/types';
import type { ResultTab, Route, View } from '../model/route';
import { acceptanceLabels, jobStatusLabels } from '../model/presentation';
import brandMark from '../assets/brand-mark.png';

const links = [
  { view: 'projects', label: '项目', icon: FolderOpen },
  { view: 'workspace', label: '结构与活性', icon: FlaskConical },
  { view: 'jobs', label: '任务记录', icon: Clock3 },
  { view: 'settings', label: '环境管理', icon: Settings },
] as const;
export function Sidebar({
  route,
  navigate,
  project,
  job,
  health,
  onUpload,
  onAnalysis,
  disabled,
  inert = false,
  collapsed = false,
}: {
  route: Route;
  navigate: (view: View) => void;
  project: Project | null;
  job: Job | null;
  health: Health | null;
  onUpload: () => void;
  onAnalysis: (tab: ResultTab) => void;
  disabled: boolean;
  inert?: boolean;
  collapsed?: boolean;
}) {
  return (
    <aside className="sidebar" id="primary-sidebar" inert={inert}>
      <a className="brand" href="#/" aria-label="X-PatentSAR 工作台">
        <img className="brand-symbol" src={brandMark} alt="" width={34} height={34} />
        <span>
          <strong>X-PatentSAR</strong>
          <small>专利结构与活性提取平台</small>
        </span>
      </a>
      <button
        className="sidebar-upload"
        type="button"
        onClick={onUpload}
        disabled={disabled}
        aria-label="新建专利项目"
        title={collapsed ? '新建专利项目' : undefined}
      >
        <SquarePlus size={18} strokeWidth={1.65} />
        <span className="nav-label">新建专利项目</span>
      </button>
      <nav aria-label="主导航">
        {links.map(({ view, label, icon: Icon }) => (
          <button
            type="button"
            key={view}
            className={`nav-item${route.view === view && (view !== 'workspace' || !route.resultTab || route.resultTab === 'results') ? ' active' : ''}`}
            aria-label={label}
            title={collapsed ? label : undefined}
            aria-current={
              route.view === view &&
              (view !== 'workspace' || !route.resultTab || route.resultTab === 'results')
                ? 'page'
                : undefined
            }
            onClick={() => navigate(view)}
          >
            <Icon size={21} />
            <span className="nav-label">{label}</span>
          </button>
        ))}
        <div className="nav-divider" />
        <button
          type="button"
          className={`nav-item${route.view === 'workspace' && route.resultTab === 'admet' ? ' active' : ''}`}
          onClick={() => onAnalysis('admet')}
          disabled={disabled}
          aria-label="分子分析 · ADMET"
          title={collapsed ? '分子分析 · ADMET' : undefined}
        >
          <ShieldCheck size={21} />
          <span className="nav-label">分子分析 · ADMET</span>
        </button>
        <button
          type="button"
          className={`nav-item${route.view === 'workspace' && route.resultTab === 'summary' ? ' active' : ''}`}
          onClick={() => onAnalysis('summary')}
          disabled={disabled}
          aria-label="证据摘要"
          title={collapsed ? '证据摘要' : undefined}
        >
          <FileText size={21} />
          <span className="nav-label">证据摘要</span>
          <span className="small-tag">确定性</span>
        </button>
      </nav>
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
        <span className="nav-label">本地工作台</span>
        <span>{health ? `v${health.product.version}` : '版本待连接'}</span>
      </footer>
    </aside>
  );
}
