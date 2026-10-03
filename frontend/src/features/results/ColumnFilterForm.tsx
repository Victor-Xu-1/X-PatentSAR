import { useState } from 'react';
import type { ActivityColumn, ColumnFilter } from '../../api/types';
import type { ResultColumn } from '../../model/resultColumns';
import {
  columnFilterDraft,
  columnFilterModes,
  compileColumnFilter,
  filterLabels,
} from '../../model/columnFilters';
import type { FilterMode } from '../../model/columnFilters';

export function ColumnFilterForm({
  column,
  activity,
  filters,
  disabled,
  onApply,
}: {
  column: ResultColumn;
  activity: ActivityColumn | undefined;
  filters: readonly ColumnFilter[];
  disabled: boolean;
  onApply: (filters: ColumnFilter[]) => void;
}) {
  const modes = columnFilterModes(
    column,
    Boolean(activity?.filter_values?.length) ||
      filters.some((filter) => filter.column === column.id && filter.op === 'in'),
  );
  const [draft, setDraft] = useState(() =>
    columnFilterDraft(column.id, filters, modes[0] ?? 'contains'),
  );
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  if (!modes.length) return null;
  const choices = activity?.filter_values ?? [];
  const available = [
    ...choices,
    ...draft.values
      .filter((value) => !choices.some((choice) => choice.value === value))
      .map((value) => ({ value, count: null })),
  ];
  const scalar = !['empty', 'not_empty', 'in'].includes(draft.op);
  return (
    <form
      className="column-filter-form"
      onSubmit={(event) => {
        event.preventDefault();
        try {
          onApply(compileColumnFilter(column.id, draft));
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : '筛选条件无效。');
        }
      }}
    >
      <label>
        筛选
        <select
          aria-label="筛选方式"
          disabled={disabled}
          value={draft.op}
          onChange={(event) => {
            setDraft({ ...draft, op: event.target.value as FilterMode });
            setError('');
          }}
        >
          {modes.map((mode) => (
            <option key={mode} value={mode}>
              {filterLabels[mode]}
            </option>
          ))}
        </select>
      </label>
      {scalar && (
        <input
          aria-label={draft.op === 'range' ? '筛选下限' : '筛选值'}
          placeholder={draft.op === 'range' ? '下限' : '值…'}
          maxLength={500}
          disabled={disabled}
          value={draft.value}
          onChange={(event) => {
            setDraft({ ...draft, value: event.target.value });
            setError('');
          }}
        />
      )}
      {draft.op === 'range' && (
        <input
          aria-label="筛选上限"
          placeholder="上限"
          maxLength={500}
          disabled={disabled}
          value={draft.upper}
          onChange={(event) => {
            setDraft({ ...draft, upper: event.target.value });
            setError('');
          }}
        />
      )}
      {draft.op === 'in' && (
        <>
          <input
            aria-label="查找筛选取值"
            placeholder="查找取值…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <fieldset className="column-value-choices" disabled={disabled}>
            <legend>全项目取值</legend>
            {available
              .filter((choice) =>
                choice.value.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
              )
              .map((choice) => (
                <label key={choice.value}>
                  <input
                    type="checkbox"
                    aria-label={`筛选值 ${choice.value}`}
                    checked={draft.values.includes(choice.value)}
                    onChange={(event) => {
                      setDraft({
                        ...draft,
                        values: event.target.checked
                          ? [...draft.values, choice.value]
                          : draft.values.filter((value) => value !== choice.value),
                      });
                      setError('');
                    }}
                  />
                  <span>{choice.value}</span>
                  <small>{choice.count ?? '已选'}</small>
                </label>
              ))}
          </fieldset>
          {activity?.filter_values_truncated && (
            <small className="muted">
              仅列出有界目录中的取值；其他取值可使用“等于”或“包含”筛选。
            </small>
          )}
        </>
      )}
      <small className="muted">筛选完整项目，不只当前页。多次观察任一匹配即保留该行。</small>
      {error && (
        <p role="alert" className="error-notice">
          {error}
        </p>
      )}
      <div className="column-menu-actions">
        <button type="submit" disabled={disabled}>
          应用筛选
        </button>
        <button
          type="button"
          disabled={disabled || !filters.some((filter) => filter.column === column.id)}
          onClick={() => onApply([])}
        >
          清除此列筛选
        </button>
      </div>
    </form>
  );
}
