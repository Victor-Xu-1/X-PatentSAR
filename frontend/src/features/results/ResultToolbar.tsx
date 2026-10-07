import { Columns3, Download, MoreHorizontal, Search } from 'lucide-react';
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
import { ColumnChooser } from './ColumnChooser';
import { TableCopyButton } from './TableCopyButton';

export function ResultToolbar({
  project,
  job,
  filters,
  display,
  columns,
  copy,
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
  columns: ComponentProps<typeof ColumnChooser>;
  copy: ComponentProps<typeof TableCopyButton>;
  selectedCount: number;
  loading: boolean;
  canExport: boolean;
  onReload: () => void;
  onExport: () => void;
  canPredict: boolean;
  onPredictionQueued: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const columnFilterCount = new Set(filters.filters.column_filters?.map((filter) => filter.column))
    .size;
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
        {columnFilterCount > 0 && (
          <button
            type="button"
            className="toolbar-button"
            disabled={filters.disabled || loading}
            aria-label="清除列筛选"
            title={`${columnFilterCount} 列已筛选（包括隐藏列）`}
            onClick={() => filters.onChange({ column_filters: [], page: 1 })}
          >
            筛选 {columnFilterCount} ×
          </button>
        )}
        {filters.filters.sort_column && (
          <button
            type="button"
            className="toolbar-button"
            disabled={filters.disabled || loading}
            aria-label="取消列排序"
            onClick={() =>
              filters.onChange({ sort_column: '', sort_direction: 'asc', sort_band: '', page: 1 })
            }
          >
            排序 ×
          </button>
        )}
        <TableCopyButton {...copy} />
        <button
          type="button"
          className="toolbar-button"
          disabled={!project}
          aria-label="显示列"
          data-column-chooser
          title={`显示 / 隐藏列（${columns.columns.length - columns.columns.filter((column) => columns.hidden.includes(column.id)).length} / ${columns.columns.length}）`}
          onClick={() => setChoosing(true)}
        >
          <Columns3 size={14} />
          <span>列设置</span>
        </button>
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
      {choosing && (
        <Dialog title="显示列" onClose={() => setChoosing(false)}>
          <ColumnChooser {...columns} />
        </Dialog>
      )}
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
