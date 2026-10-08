import { useTranslation } from '../../i18n';
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
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const columnFilterCount = new Set(filters.filters.column_filters?.map((filter) => filter.column))
    .size;
  return (
    <>
      <header className="result-toolbar" aria-label={t('结构列表工具栏')}>
        <h2 className="sr-only">{t('结构列表')}</h2>
        <label className="search-field result-search">
          <Search size={14} />
          <input
            aria-label={t('搜索结果')}
            data-dialog-focus-fallback
            value={filters.filters.q}
            placeholder={t('搜索编号、靶点或活性…')}
            disabled={filters.disabled}
            onChange={(event) => filters.onChange({ q: event.target.value, page: 1 })}
          />
        </label>
        {selectedCount > 0 && (
          <span className="selection-count">{t('已选 {count}', { count: selectedCount })}</span>
        )}
        {columnFilterCount > 0 && (
          <button
            type="button"
            className="toolbar-button"
            disabled={filters.disabled || loading}
            aria-label={t('清除列筛选')}
            title={t('{count} 列已筛选（包括隐藏列）', { count: columnFilterCount })}
            onClick={() => filters.onChange({ column_filters: [], page: 1 })}
          >
            {t('筛选 {count} ×', { count: columnFilterCount })}
          </button>
        )}
        {filters.filters.sort_column && (
          <button
            type="button"
            className="toolbar-button"
            disabled={filters.disabled || loading}
            aria-label={t('取消列排序')}
            onClick={() =>
              filters.onChange({ sort_column: '', sort_direction: 'asc', sort_band: '', page: 1 })
            }
          >
            {t('排序 ×')}
          </button>
        )}
        <TableCopyButton {...copy} />
        <button
          type="button"
          className="toolbar-button"
          disabled={!project}
          aria-label={t('显示列')}
          data-column-chooser
          title={t('显示 / 隐藏列（{visible} / {total}）', {
            visible:
              columns.columns.length -
              columns.columns.filter((column) => columns.hidden.includes(column.id)).length,
            total: columns.columns.length,
          })}
          onClick={() => setChoosing(true)}
        >
          <Columns3 size={14} />
          <span>{t('列设置')}</span>
        </button>
        <button
          type="button"
          className="toolbar-button"
          disabled={!canExport}
          onClick={onExport}
          aria-label={
            selectedCount ? t('导出所选 ({count})', { count: selectedCount }) : t('导出结果')
          }
        >
          <Download size={14} />
          {t('导出')}
        </button>
        <button
          type="button"
          className="toolbar-button"
          disabled={!project}
          aria-label={t('列表选项')}
          title={t('筛选、显示与结果详情')}
          onClick={() => setOpen(true)}
        >
          <MoreHorizontal size={14} />
        </button>
      </header>
      {choosing && (
        <Dialog title={t('显示列')} onClose={() => setChoosing(false)}>
          <ColumnChooser {...columns} />
        </Dialog>
      )}
      {open && (
        <Dialog title={t('列表选项')} onClose={() => setOpen(false)}>
          <div className="dialog-body result-options">
            <ResultFilters {...filters} />
            <details>
              <summary>{t('显示选项')}</summary>
              <ResultDisplayControls {...display} />
            </details>
            <details>
              <summary>{t('结果与验收详情')}</summary>
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
              {t('刷新真实提取结果')}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
