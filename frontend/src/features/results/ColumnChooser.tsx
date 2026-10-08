import { useTranslation } from '../../i18n';
import { useState } from 'react';
import type { ResultColumn } from '../../model/resultColumns';

export function ColumnChooser({
  columns,
  hidden,
  onHidden,
}: {
  columns: ResultColumn[];
  hidden: readonly string[];
  onHidden: (hidden: string[]) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const visible = columns.filter((column) =>
    [column.label, column.context]
      .filter(Boolean)
      .join(' ')
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  return (
    <div className="dialog-body column-chooser">
      <input
        aria-label={t('查找列')}
        placeholder={t('查找列…')}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <button type="button" onClick={() => onHidden([])}>
        {t('显示全部列')}
      </button>
      <fieldset>
        <legend className="sr-only">{t('可显示的全部项目列')}</legend>
        {visible.map((column) => (
          <label key={column.id}>
            <input
              type="checkbox"
              aria-label={t('显示列 {column}', {
                column: [column.label, column.context].filter(Boolean).join(' · '),
              })}
              checked={!hidden.includes(column.id)}
              onChange={(event) =>
                onHidden(
                  event.target.checked
                    ? hidden.filter((id) => id !== column.id)
                    : [...hidden, column.id],
                )
              }
            />
            <span>
              {column.label}
              {column.context && <small>{column.context}</small>}
            </span>
          </label>
        ))}
        {!visible.length && <p className="muted">{t('没有匹配的列')}</p>}
      </fieldset>
      <small className="muted">
        {t('仅改变当前工作台显示，不删除数据，不改变全项目导出或活性分档。')}
      </small>
    </div>
  );
}
