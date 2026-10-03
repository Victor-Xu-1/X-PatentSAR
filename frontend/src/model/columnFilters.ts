import type { ColumnFilter } from '../api/types';
import type { ResultColumn } from './resultColumns';

export type FilterMode = ColumnFilter['op'] | 'range';
export interface FilterDraft {
  op: FilterMode;
  value: string;
  upper: string;
  values: string[];
}
export const filterLabels: Record<FilterMode, string> = {
  contains: '包含',
  eq: '等于',
  gt: '大于',
  gte: '大于或等于',
  lt: '小于',
  lte: '小于或等于',
  in: '选择取值',
  empty: '为空',
  not_empty: '非空',
  range: '范围（含边界）',
};
export function columnCanSort(column: ResultColumn): boolean {
  return !['select', 'structure'].includes(column.id) && !column.id.includes('legacy:');
}
export function columnFilterModes(column: ResultColumn, hasValues: boolean): FilterMode[] {
  if (column.id === 'select' || column.id.includes('legacy:')) return [];
  if (column.id === 'structure') return ['empty', 'not_empty'];
  const numeric = column.id.startsWith('property:') || column.id === 'source';
  return [
    ...(numeric ? [] : (['contains'] as const)),
    'eq',
    ...(numeric || column.id.startsWith('activity:')
      ? (['gt', 'gte', 'lt', 'lte', 'range'] as const)
      : []),
    ...(hasValues ? (['in'] as const) : []),
    'empty',
    'not_empty',
  ];
}
export function columnFilterDraft(
  column: string,
  filters: readonly ColumnFilter[],
  fallback: FilterMode,
): FilterDraft {
  const own = filters.filter((filter) => filter.column === column);
  const lower = own.find((filter) => filter.op === 'gte');
  const upper = own.find((filter) => filter.op === 'lte');
  if (own.length === 2 && lower && upper)
    return { op: 'range', value: lower.value ?? '', upper: upper.value ?? '', values: [] };
  const first = own[0];
  return {
    op: first?.op ?? fallback,
    value: first?.value ?? '',
    upper: '',
    values: first?.values ?? [],
  };
}
export function compileColumnFilter(column: string, draft: FilterDraft): ColumnFilter[] {
  if (draft.op === 'empty' || draft.op === 'not_empty') return [{ column, op: draft.op }];
  if (draft.op === 'in') {
    if (!draft.values.length) throw new Error('至少选择一个取值；如需查看空值，请选择“为空”。');
    return [{ column, op: 'in', values: [...draft.values] }];
  }
  const value = draft.value.trim();
  if (!value) throw new Error('请输入筛选值。');
  const numeric = column.startsWith('property:') || column === 'source';
  const finiteScalar = (text: string) =>
    /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(text) && Number.isFinite(Number(text));
  if (
    draft.op === 'range' ||
    ['gt', 'gte', 'lt', 'lte'].includes(draft.op) ||
    (numeric && draft.op === 'eq')
  ) {
    if (!finiteScalar(value)) throw new Error('比较条件需要有限数值，不能使用等级或区间文本。');
  }
  if (draft.op === 'range') {
    const upper = draft.upper.trim();
    if (!finiteScalar(upper)) throw new Error('请输入有效的筛选上限。');
    if (Number(value) > Number(upper)) throw new Error('筛选下限不能大于上限。');
    return [
      { column, op: 'gte', value },
      { column, op: 'lte', value: upper },
    ];
  }
  return [{ column, op: draft.op, value }];
}
export function replaceColumnFilters(
  filters: readonly ColumnFilter[],
  column: string,
  replacement: ColumnFilter[],
): ColumnFilter[] {
  return [...filters.filter((filter) => filter.column !== column), ...replacement];
}
