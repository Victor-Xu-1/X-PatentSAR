import { FolderOpen, Menu, PanelLeftClose, PanelLeftOpen, Upload, X } from 'lucide-react';
import type { Project } from '../api/types';
import type { View } from '../model/route';
const viewLabels: Record<View, string> = {
  workspace: '结构与活性工作台',
  projects: '项目管理',
  jobs: '任务记录',
  settings: '环境管理',
  'new-task': '新建提取任务',
};
export function Header({
  view,
  project,
  user,
  onUpload,
  onMenu,
  disabled,
  menuOpen,
  contentInert = false,
  mobile = false,
  navigationCollapsed = false,
}: {
  view: View;
  project: Project | null;
  user: string | null;
  onUpload: () => void;
  onMenu: () => void;
  disabled: boolean;
  menuOpen: boolean;
  contentInert?: boolean;
  mobile?: boolean;
  navigationCollapsed?: boolean;
}) {
  return (
    <header className="topbar">
      <button
        type="button"
        className="icon-button menu-toggle"
        aria-label={mobile ? '展开或收起导航' : navigationCollapsed ? '展开导航栏' : '收起导航栏'}
        aria-expanded={mobile ? menuOpen : !navigationCollapsed}
        aria-controls="primary-sidebar"
        onClick={onMenu}
      >
        {mobile ? (
          menuOpen ? (
            <X size={20} />
          ) : (
            <Menu size={20} />
          )
        ) : navigationCollapsed ? (
          <PanelLeftOpen size={17} />
        ) : (
          <PanelLeftClose size={17} />
        )}
      </button>
      <nav className="breadcrumb" aria-label="面包屑" inert={contentInert}>
        <FolderOpen size={20} />
        <a href="#/projects">项目</a>
        <span>/</span>
        <strong title={project?.title}>
          {view === 'workspace' && project ? project.title : viewLabels[view]}
        </strong>
      </nav>
      <div className="topbar-actions" inert={contentInert}>
        <button type="button" aria-label="上传 PDF" onClick={onUpload} disabled={disabled}>
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
