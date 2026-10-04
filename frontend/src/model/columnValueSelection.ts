import type { ColumnFilter } from '../api/types';

export interface ValueSelection {
  mode: 'include' | 'exclude';
  values: string[];
  includeEmpty: boolean;
}
export function restoreValueSelection(
  column: string,
  filters: readonly ColumnFilter[],
): ValueSelection {
  const filter = filters.find(
    (item) => item.column === column && ['in', 'not_in'].includes(item.op),
  );
  const exclude = !filter || filter.op === 'not_in';
  return {
    mode: exclude ? 'exclude' : 'include',
    values: [...(filter?.values ?? [])],
    includeEmpty: filter?.include_empty ?? exclude,
  };
}
export function valueIsSelected(selection: ValueSelection, value: string): boolean {
  const listed = selection.values.includes(value);
  return selection.mode === 'include' ? listed : !listed;
}
export function setSelectedValues(
  selection: ValueSelection,
  values: readonly string[],
  checked: boolean,
): ValueSelection {
  const next = new Set(selection.values);
  for (const value of values) {
    if (checked === (selection.mode === 'include')) next.add(value);
    else next.delete(value);
  }
  if (next.size > 200)
    throw new Error('最多保留 200 个显式选择或排除值；请缩小搜索或使用条件筛选。');
  return { ...selection, values: [...next] };
}
export function compileValueSelection(column: string, selection: ValueSelection): ColumnFilter[] {
  if (selection.values.length > 200) throw new Error('最多保留 200 个显式选择或排除值。');
  if (selection.mode === 'exclude' && !selection.values.length && selection.includeEmpty) return [];
  return [
    {
      column,
      op: selection.mode === 'include' ? 'in' : 'not_in',
      values: [...selection.values],
      include_empty: selection.includeEmpty,
    },
  ];
}
