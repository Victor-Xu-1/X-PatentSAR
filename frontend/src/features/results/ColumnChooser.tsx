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
        aria-label="查找列"
        placeholder="查找列…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <button type="button" onClick={() => onHidden([])}>
        显示全部列
      </button>
      <fieldset>
        <legend className="sr-only">可显示的全部项目列</legend>
        {visible.map((column) => (
          <label key={column.id}>
            <input
              type="checkbox"
              aria-label={`显示列 ${[column.label, column.context].filter(Boolean).join(' · ')}`}
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
        {!visible.length && <p className="muted">没有匹配的列</p>}
      </fieldset>
      <small className="muted">
        仅改变当前工作台显示，不删除数据，不改变全项目导出或活性分档。
      </small>
    </div>
  );
}
