import { FolderOpen, Menu, Search, Upload } from 'lucide-react';
import type { Project } from '../api/types';
import type { View } from '../model/route';
const viewLabels: Record<View, string> = {
  workspace: '结构与活性工作台',
  projects: '项目管理',
  jobs: '任务记录',
  settings: '运行环境',
};
export function Header({
  view,
  project,
  user,
  query,
  onQuery,
  onUpload,
  onMenu,
  disabled,
  menuOpen,
}: {
  view: View;
  project: Project | null;
  user: string | null;
  query: string;
  onQuery: (value: string) => void;
  onUpload: () => void;
  onMenu: () => void;
  disabled: boolean;
  menuOpen: boolean;
}) {
  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-button menu-toggle"
        aria-label="展开或收起导航"
        aria-expanded={menuOpen}
        aria-controls="primary-sidebar"
        onClick={onMenu}
      >
        <Menu size={20} />
      </button>
      <nav className="breadcrumb" aria-label="面包屑">
        <FolderOpen size={20} />
        <a href="#/projects">项目</a>
        <span>/</span>
        <strong title={project?.title}>
          {view === 'workspace' && project ? project.title : viewLabels[view]}
        </strong>
      </nav>
      <div className="topbar-actions">
        <label className="search-field global-search">
          <Search size={16} />
          <input
            aria-label="搜索关键词、化合物编号或靶点"
            placeholder="搜索关键词、化合物编号或靶点…"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            disabled={disabled || view !== 'workspace' || !project}
          />
        </label>
        <button type="button" onClick={onUpload} disabled={disabled}>
          <Upload size={16} />
          <span>上传 PDF</span>
        </button>
        <span
          className="user-avatar"
          title={user ?? '尚未连接本地会话'}
          aria-label={user ?? '尚未连接本地会话'}
        >
          {user?.slice(0, 1).toUpperCase() ?? '—'}
        </span>
      </div>
    </header>
  );
}
