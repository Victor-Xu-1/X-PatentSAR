import { useState } from 'react';
import { Dialog } from '../../../components/Dialog';
import { ColumnChooser } from '../../results/ColumnChooser';
import type { ResultColumn } from '../../../model/resultColumns';
import { useTranslation } from '../../../i18n';
import type { PageSort } from './tablePresentation';
export function StudyTableControls({
  columns,
  hidden,
  onHidden,
  sort,
  onSort,
}: {
  columns: ResultColumn[];
  hidden: string[];
  onHidden: (ids: string[]) => void;
  sort: PageSort;
  onSort: (sort: PageSort) => void;
}) {
  const { t } = useTranslation(),
    [open, setOpen] = useState(false);
  return (
    <div className="sar-actions sar-study-table-controls">
      <button type="button" onClick={() => setOpen(true)}>
        {t('列设置')}
      </button>
      <label>
        {t('排序（全部研究行）')}
        <select value={sort.column} onChange={(e) => onSort({ ...sort, column: e.target.value })}>
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
          onChange={(e) => onSort({ ...sort, direction: e.target.value as PageSort['direction'] })}
        >
          <option value="asc">{t('升序')}</option>
          <option value="desc">{t('降序')}</option>
        </select>
      </label>
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
    </div>
  );
}
