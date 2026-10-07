import { Clock3, FileText, History, Settings, Upload } from 'lucide-react';
import type { Project } from '../api/types';
import type { ResultTab, View } from '../model/route';
import brandMark from '../assets/brand-mark.png';

export function Header({
  view,
  project,
  version,
  onUpload,
  onRecent,
  onNavigate,
  onAnalysis,
  disabled,
}: {
  view: View;
  project: Project | null;
  version: string | number | null;
  onUpload: () => void;
  onRecent: () => void;
  onNavigate: (view: View) => void;
  onAnalysis: (tab: ResultTab) => void;
  disabled: boolean;
}) {
  return (
    <header className="topbar">
      <a
        className="brand"
        href={disabled ? undefined : '#/new-task'}
        role={disabled ? 'link' : undefined}
        aria-label="X-PatentSAR · 上传 PDF"
        aria-disabled={disabled || undefined}
        tabIndex={disabled ? -1 : undefined}
        onClick={(event) => {
          event.preventDefault();
          if (!disabled) onUpload();
        }}
      >
        <img className="brand-symbol" src={brandMark} alt="" width={30} height={30} />
        <strong>X-PatentSAR</strong>
      </a>
      <nav className="topbar-actions" aria-label="工作台导航">
        <button
          type="button"
          aria-label="上传 PDF"
          onClick={onUpload}
          disabled={disabled}
          aria-current={view === 'new-task' ? 'page' : undefined}
        >
          <Upload size={15} />
          <span>上传 PDF</span>
        </button>
        <button
          type="button"
          aria-label="最近文件"
          onClick={onRecent}
          disabled={disabled}
          aria-current={view === 'projects' ? 'page' : undefined}
        >
          <History size={15} />
          <span>最近文件</span>
        </button>
        <button
          type="button"
          aria-label="环境管理"
          disabled={disabled}
          onClick={() => onNavigate('settings')}
          aria-current={view === 'settings' ? 'page' : undefined}
        >
          <Settings size={15} />
          <span>环境管理</span>
        </button>
        <button
          type="button"
          aria-label="任务记录"
          disabled={disabled}
          onClick={() => onNavigate('jobs')}
          aria-current={view === 'jobs' ? 'page' : undefined}
        >
          <Clock3 size={15} />
          <span>任务记录</span>
        </button>
        {project && view === 'workspace' && (
          <>
            <button
              type="button"
              aria-label="返回结果表格"
              disabled={disabled}
              onClick={() => onAnalysis('results')}
            >
              <FileText size={15} />
              <span>结果表格</span>
            </button>
            <button
              type="button"
              aria-label="证据摘要"
              disabled={disabled}
              onClick={() => onAnalysis('summary')}
            >
              <span>证据摘要</span>
            </button>
          </>
        )}
      </nav>
      <small className="topbar-version" aria-label="软件版本">
        {version !== null ? `v${version}` : '版本待连接'}
      </small>
    </header>
  );
}
