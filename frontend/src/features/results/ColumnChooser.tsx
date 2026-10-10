import { useTranslation } from '../../i18n';
import { useId, useState } from 'react';
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
  const [details, setDetails] = useState(false);
  const listId = useId();
  const labels = new Map<string, number>();
  for (const column of columns) labels.set(column.label, (labels.get(column.label) ?? 0) + 1);
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
        data-initial-focus
        aria-label={t('查找列')}
        placeholder={t('查找列…')}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div className="column-chooser-actions">
        <button type="button" onClick={() => onHidden([])}>
          {t('显示全部列')}
        </button>
        <button
          type="button"
          aria-expanded={details}
          aria-controls={listId}
          onClick={() => setDetails(!details)}
        >
          {t('列详情')}
        </button>
      </div>
      <fieldset id={listId}>
        <legend className="sr-only">{t('可显示的全部项目列')}</legend>
        {visible.map((column) => (
          <label key={column.id} className="column-chooser-choice">
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
              {column.context && (details || (labels.get(column.label) ?? 0) > 1) && (
                <small className="column-chooser-context">{column.context}</small>
              )}
            </span>
          </label>
        ))}
        {!visible.length && <p className="muted">{t('没有匹配的列')}</p>}
      </fieldset>
      <small className="muted">{t('仅影响显示')}</small>
    </div>
  );
}
