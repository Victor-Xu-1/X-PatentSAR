import { useId, useState } from 'react';
import { Columns3, Search, SlidersHorizontal } from 'lucide-react';
import type { StudyFilter, StudyReport } from '../../../api/sarStudyTypes';
import { Dialog } from '../../../components/Dialog';
import { ColumnChooser } from '../../results/ColumnChooser';
import type { ResultColumn } from '../../../model/resultColumns';
import { useTranslation } from '../../../i18n';
import type { PageSort } from './tablePresentation';
import { StudyTableFilters } from './StudyTableFilters';
export function StudyTableControls({
  report,
  filter,
  onFilter,
  columns,
  hidden,
  onHidden,
  sort,
  onSort,
}: {
  report: StudyReport;
  filter: StudyFilter;
  onFilter: (filter: StudyFilter) => void;
  columns: ResultColumn[];
  hidden: string[];
  onHidden: (ids: string[]) => void;
  sort: PageSort;
  onSort: (sort: PageSort) => void;
}) {
  const { t } = useTranslation(),
    [open, setOpen] = useState(false),
    [optionsOpen, setOptionsOpen] = useState(false);
  const optionsId = useId();
  const optionCount = [
    filter.scope !== 'all',
    filter.scaffold_id,
    filter.region_id,
    filter.fragment_id,
    sort.column || sort.direction !== 'asc',
  ].filter(Boolean).length;
  return (
    <>
      <div className="sar-study-table-toolbar">
        <label className="sar-study-search">
          <span className="sr-only">{t('搜索编号或 SMILES')}</span>
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            maxLength={200}
            value={filter.query}
            placeholder={t('搜索编号或 SMILES')}
            onChange={(e) => onFilter({ ...filter, query: e.target.value })}
          />
        </label>
        <button type="button" onClick={() => setOpen(true)}>
          <Columns3 size={16} aria-hidden="true" />
          {t('列设置')}
        </button>
        <button
          type="button"
          aria-label={t('筛选与排序')}
          aria-expanded={optionsOpen}
          aria-controls={optionsId}
          data-active={optionCount > 0 || undefined}
          onClick={() => setOptionsOpen(!optionsOpen)}
        >
          <SlidersHorizontal size={16} aria-hidden="true" />
          {t('筛选与排序')}
          {optionCount > 0 && (
            <output aria-label={t('已启用 {count} 项表格选项', { count: optionCount })}>
              {optionCount}
            </output>
          )}
        </button>
      </div>
      <section
        id={optionsId}
        className="sar-study-table-options"
        aria-label={t('表格选项')}
        hidden={!optionsOpen}
      >
        <StudyTableFilters report={report} filter={filter} onFilter={onFilter} />
        <div className="sar-actions sar-study-table-controls">
          <label>
            {t('排序（全部研究行）')}
            <select
              value={sort.column}
              onChange={(e) => onSort({ ...sort, column: e.target.value })}
            >
              <option value="">{t('服务器自然编号顺序')}</option>
              {columns
                .filter((c) => !['structure', 'source'].includes(c.id))
                .map((c) => (
                  <option value={c.id} key={c.id}>
                    {c.label}
                  </option>
                ))}
            </select>
          </label>
          <label>
            {t('排序方向')}
            <select
              value={sort.direction}
              onChange={(e) =>
                onSort({ ...sort, direction: e.target.value as PageSort['direction'] })
              }
            >
              <option value="asc">{t('升序')}</option>
              <option value="desc">{t('降序')}</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => {
              onFilter({
                ...filter,
                scope: 'all',
                scaffold_id: '',
                region_id: '',
                fragment_id: '',
              });
              onSort({ column: '', direction: 'asc' });
            }}
          >
            {t('重置筛选与排序')}
          </button>
        </div>
      </section>
      {open && (
        <Dialog title={t('列设置')} onClose={() => setOpen(false)}>
          <ColumnChooser columns={columns} hidden={hidden} onHidden={onHidden} />
          <footer className="dialog-actions">
            <button type="button" onClick={() => setOpen(false)}>
              {t('关闭对话框')}
            </button>
          </footer>
        </Dialog>
      )}
    </>
  );
}
