import { useEffect, useRef, useState } from 'react';
import { Clock3, FileText, History, MoreHorizontal, Settings, Upload } from 'lucide-react';
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
  const menu = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (event.target instanceof Node && !menu.current?.contains(event.target))
        menu.current?.removeAttribute('open');
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        menu.current?.removeAttribute('open');
        menu.current?.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);
  function select(action: () => void) {
    menu.current?.removeAttribute('open');
    menu.current?.querySelector('summary')?.focus();
    action();
  }
  const title = view === 'workspace' ? (project?.title ?? '正在打开文件…') : '';
  return (
    <header className="topbar">
      <a
        className="brand"
        href="#/new-task"
        aria-label="X-PatentSAR · 上传 PDF"
        onClick={(event) => {
          event.preventDefault();
          onUpload();
        }}
      >
        <img className="brand-symbol" src={brandMark} alt="" width={25} height={25} />
        <strong>X-PatentSAR</strong>
      </a>
      {title && (
        <span className="document-title" title={title}>
          {title}
        </span>
      )}
      <nav className="topbar-actions" aria-label="文件操作">
        <button type="button" aria-label="上传 PDF" onClick={onUpload} disabled={disabled}>
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
        <details
          className="shell-menu"
          ref={menu}
          onToggle={(event) => setOpen(event.currentTarget.open)}
        >
          <summary aria-label="更多" title="更多" aria-expanded={open}>
            <MoreHorizontal size={18} />
          </summary>
          <div className="shell-menu-content">
            <button
              type="button"
              disabled={disabled}
              onClick={() => select(() => onNavigate('settings'))}
            >
              <Settings size={15} />
              环境管理
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => select(() => onNavigate('jobs'))}
            >
              <Clock3 size={15} />
              任务记录
            </button>
            {project && view === 'workspace' && (
              <>
                <button type="button" onClick={() => select(() => onAnalysis('results'))}>
                  <FileText size={15} />
                  返回结果表格
                </button>
                <button type="button" onClick={() => select(() => onAnalysis('summary'))}>
                  证据摘要
                </button>
              </>
            )}
            <small>{version !== null ? `v${version}` : '版本待连接'}</small>
          </div>
        </details>
      </nav>
    </header>
  );
}
