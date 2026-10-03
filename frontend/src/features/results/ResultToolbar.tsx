import { Download, Filter, Info, RefreshCw, Search, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import type { ComponentProps } from 'react';
import type { Job, Project } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { ExtractionNotice } from './ExtractionNotice';
import { Metrics } from './Metrics';
import { ResultDisplayControls } from './ResultDisplayControls';
import { ResultFilters } from './ResultFilters';

type Panel = 'filters' | 'display' | 'info';
const titles: Record<Panel, string> = {
  filters: '筛选结果',
  display: '显示选项',
  info: '结果信息',
};

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
}) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const failed = project?.acceptance.state === 'failed' || job?.status === 'failed';
  const stateLabel = failed
    ? '未通过'
    : project?.acceptance.state === 'accepted'
      ? '已验收'
      : project?.is_historical
        ? '历史'
        : '待验收';
  const activeFilters = [
    filters.filters.target,
    filters.filters.confidence,
    filters.filters.review,
  ].filter(Boolean).length;
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
            placeholder="搜索编号或靶点…"
            disabled={filters.disabled}
            onChange={(event) => filters.onChange({ q: event.target.value, page: 1 })}
          />
        </label>
        {project && (
          <button
            type="button"
            className={`acceptance-chip ${failed ? 'failed' : project.acceptance.state}`}
            aria-label="提取验收详情"
            title="查看实际验收状态"
            onClick={() => setPanel('info')}
          >
            {stateLabel}
          </button>
        )}
        {selectedCount > 0 && <span className="selection-count">已选 {selectedCount}</span>}
        <button
          type="button"
          className="toolbar-button"
          aria-label="筛选结果"
          title="筛选结果"
          disabled={filters.disabled}
          onClick={() => setPanel('filters')}
        >
          <Filter size={14} />
          {activeFilters > 0 && <span>{activeFilters}</span>}
        </button>
        <button
          type="button"
          className="toolbar-button"
          aria-label="显示选项"
          title="显示选项"
          disabled={display.disabled}
          onClick={() => setPanel('display')}
        >
          <SlidersHorizontal size={14} />
        </button>
        <button
          type="button"
          className="toolbar-button"
          aria-label="结果信息"
          title="结果信息"
          disabled={!project}
          onClick={() => setPanel('info')}
        >
          <Info size={14} />
        </button>
        <button
          type="button"
          className="toolbar-button"
          aria-label="刷新真实提取结果"
          title="刷新结果"
          disabled={!project || loading}
          onClick={onReload}
        >
          <RefreshCw size={14} />
        </button>
        <button
          type="button"
          className="toolbar-button"
          aria-label={selectedCount ? `导出所选 (${selectedCount})` : '导出结果'}
          title="导出结果"
          disabled={!canExport}
          onClick={onExport}
        >
          <Download size={14} />
        </button>
      </header>
      {panel && (
        <Dialog title={titles[panel]} onClose={() => setPanel(null)}>
          <div className={`dialog-body result-options result-options-${panel}`}>
            {panel === 'filters' ? (
              <ResultFilters {...filters} />
            ) : panel === 'display' ? (
              <ResultDisplayControls {...display} />
            ) : (
              <>
                <Metrics project={project} />
                {project && <ExtractionNotice project={project} job={job} />}
              </>
            )}
          </div>
        </Dialog>
      )}
    </>
  );
}
