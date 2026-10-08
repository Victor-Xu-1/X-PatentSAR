import { useTranslation, UiError } from '../../i18n';
import { useEffect, useRef } from 'react';
import type { FilterValues } from '../../api/types';
import { setSelectedValues, valueIsSelected } from '../../model/columnValueSelection';
import type { ValueSelection } from '../../model/columnValueSelection';

export function ColumnValueChecklist({
  choices,
  selection,
  search,
  page,
  disabled,
  onSearch,
  onPage,
  onChange,
  onError,
}: {
  choices: FilterValues | null;
  selection: ValueSelection;
  search: string;
  page: number;
  disabled: boolean;
  onSearch: (search: string) => void;
  onPage: (page: number) => void;
  onChange: (selection: ValueSelection) => void;
  onError: (error: Error) => void;
}) {
  const { t } = useTranslation();
  const selectAll = useRef<HTMLInputElement>(null);
  const items = choices?.items ?? [];
  const searching = Boolean(search);
  const checked = items.map((item) => valueIsSelected(selection, item.value));
  const complete = Boolean(choices && page === 1 && items.length === choices.total);
  const all = searching
    ? checked.length > 0 && checked.every(Boolean)
    : (selection.mode === 'exclude' && selection.values.length === 0 && selection.includeEmpty) ||
      (complete && checked.every(Boolean) && selection.includeEmpty);
  const some = searching
    ? checked.some(Boolean)
    : complete
      ? checked.some(Boolean) || selection.includeEmpty
      : selection.mode === 'exclude' || selection.values.length > 0 || selection.includeEmpty;
  useEffect(() => {
    if (selectAll.current) selectAll.current.indeterminate = some && !all;
  }, [some, all]);
  function changeValues(values: string[], next: boolean) {
    try {
      onChange(setSelectedValues(selection, values, next));
    } catch (error) {
      onError(error instanceof Error ? error : new UiError('选择超过限额。'));
    }
  }
  const pages = Math.max(1, Math.ceil((choices?.total ?? 0) / 200));
  return (
    <div className="column-checklist">
      <input
        aria-label={t('查找筛选取值')}
        placeholder={t('搜索仅查找取值')}
        maxLength={500}
        value={search}
        onChange={(event) => onSearch(event.target.value)}
      />
      <fieldset className="column-value-choices" disabled={disabled || !choices}>
        <legend className="sr-only">{t('取值选择')}</legend>
        <label className="column-select-all">
          <input
            ref={selectAll}
            type="checkbox"
            aria-label={searching ? t('全选本页匹配取值') : t('全选筛选取值')}
            checked={all}
            disabled={searching && !items.length}
            onChange={(event) => {
              if (searching)
                changeValues(
                  items.map((item) => item.value),
                  event.target.checked,
                );
              else
                onChange({
                  mode: event.target.checked ? 'exclude' : 'include',
                  values: [],
                  includeEmpty: event.target.checked,
                });
            }}
          />
          <span>{searching ? t('全选（本页匹配）') : t('全选')}</span>
        </label>
        <label>
          <input
            type="checkbox"
            aria-label={t('筛选值（空白）')}
            checked={selection.includeEmpty}
            onChange={(event) => onChange({ ...selection, includeEmpty: event.target.checked })}
          />
          <span>{t('（空白）')}</span>
          <small>{choices?.empty_count ?? '—'}</small>
        </label>
        {items.map((item) => (
          <label key={item.value}>
            <input
              type="checkbox"
              aria-label={t('筛选值 {value}', { value: item.value })}
              checked={valueIsSelected(selection, item.value)}
              onChange={(event) => changeValues([item.value], event.target.checked)}
            />
            <span>{item.value}</span>
            <small>{item.count}</small>
          </label>
        ))}
        {choices && !items.length && (
          <small className="muted">{searching ? t('无匹配取值') : t('无非空取值')}</small>
        )}
      </fieldset>
      {choices && pages > 1 && (
        <div className="column-choice-pages" aria-label={t('取值分页')}>
          <button
            type="button"
            disabled={disabled || page <= 1}
            onClick={() => onPage(page - 1)}
            aria-label={t('上一页取值')}
          >
            ‹
          </button>
          <small>
            {t('{page} / {pages} · {total} 个取值', { page, pages, total: choices.total })}
          </small>
          <button
            type="button"
            disabled={disabled || page >= pages}
            onClick={() => onPage(page + 1)}
            aria-label={t('下一页取值')}
          >
            ›
          </button>
        </div>
      )}
      <small
        className="muted"
        title={t(
          '搜索不改变筛选；确定保留各页的显式选择。未搜索时全选控制全部值；搜索时仅控制本页匹配值。',
        )}
      >
        {t('跨页保留选择 · 最多 200 个显式选择 / 排除')}
      </small>
    </div>
  );
}
