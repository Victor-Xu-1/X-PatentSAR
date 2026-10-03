import { Download, MoreHorizontal, Search } from 'lucide-react';
import { useState } from 'react';
import type { ComponentProps } from 'react';
import type { Job, Project } from '../../api/types';
import { activeJob } from '../../model/presentation';
import { Dialog } from '../../components/Dialog';
import { ExtractionNotice } from './ExtractionNotice';
import { Metrics } from './Metrics';
import { ResultDisplayControls } from './ResultDisplayControls';
import { ResultFilters } from './ResultFilters';
import { PredictionAction } from './PredictionAction';

export function ResultToolbar({
  project,
  job,
  filters,
  display,
  selectedCount,
  loading,
  canExport,
  onReload,
  onExport,
  canPredict,
  onPredictionQueued,
}: {
  project: Project | null;
  job: Job | null;
  filters: ComponentProps<typeof ResultFilters>;
  display: ComponentProps<typeof ResultDisplayControls>;
  selectedCount: number;
  loading: boolean;
  canExport: boolean;
  onReload: () => void;
  onExport: () => void;
  canPredict: boolean;
  onPredictionQueued: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <header className="result-toolbar" aria-label="结构列表工具栏">
        <h2 className="sr-only">结构列表</h2>
        <label className="search-field result-search">
          <Search size={14} />
          <input
            aria-label="搜索结果"
            data-dialog-focus-fallback
            value={filters.filters.q}
            placeholder="搜索编号、靶点或活性…"
            disabled={filters.disabled}
            onChange={(event) => filters.onChange({ q: event.target.value, page: 1 })}
          />
        </label>
        {selectedCount > 0 && <span className="selection-count">已选 {selectedCount}</span>}
        <button
          type="button"
          className="toolbar-button"
          disabled={!canExport}
          onClick={onExport}
          aria-label={selectedCount ? `导出所选 (${selectedCount})` : '导出结果'}
        >
          <Download size={14} />
          导出
        </button>
        <button
          type="button"
          className="toolbar-button"
          disabled={!project}
          aria-label="列表选项"
          title="筛选、显示与结果详情"
          onClick={() => setOpen(true)}
        >
          <MoreHorizontal size={14} />
        </button>
      </header>
      {open && (
        <Dialog title="列表选项" onClose={() => setOpen(false)}>
          <div className="dialog-body result-options">
            <ResultFilters {...filters} />
            <details>
              <summary>显示选项</summary>
              <ResultDisplayControls {...display} />
            </details>
            <details>
              <summary>结果与验收详情</summary>
              <Metrics project={project} />
              {project && <ExtractionNotice project={project} job={job} />}
            </details>
            {project && (
              <PredictionAction
                projectId={project.id}
                disabled={!canPredict || Boolean(job && activeJob(job))}
                onQueued={onPredictionQueued}
              />
            )}
            <button
              type="button"
              disabled={!project || loading}
              onClick={() => {
                onReload();
                setOpen(false);
              }}
            >
              刷新真实提取结果
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
