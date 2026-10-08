import { UiError } from '../i18n';
import type { ActivityColumn, ColumnFilter, FilterValueKind } from '../api/types';
import type { ResultColumn } from './resultColumns';

export type FilterMode = Exclude<ColumnFilter['op'], 'in' | 'not_in' | 'band'> | 'range';
export interface FilterDraft {
  op: FilterMode;
  value: string;
  upper: string;
}
export const filterLabels: Record<FilterMode, string> = {
  contains: '包含',
  not_contains: '不包含',
  starts_with: '开头是',
  ends_with: '结尾是',
  eq: '等于',
  ne: '不等于',
  gt: '大于',
  gte: '大于或等于',
  lt: '小于',
  lte: '小于或等于',
  empty: '为空',
  not_empty: '非空',
  range: '范围（含边界）',
};
export function columnCanSort(column: ResultColumn): boolean {
  return !['select', 'structure'].includes(column.id) && !column.id.includes('legacy:');
}
export function columnCanFilter(column: ResultColumn): boolean {
  return column.id !== 'select' && !column.id.includes('legacy:');
}
export function defaultColumnKind(
  column: ResultColumn,
  activity?: ActivityColumn,
): FilterValueKind {
  if (column.id === 'structure') return 'presence';
  if (
    column.id.startsWith('property:') ||
    column.id === 'source' ||
    activity?.strength_scale?.kind === 'numeric'
  )
    return 'number';
  return 'text';
}
export function columnFilterModes(kind: FilterValueKind): FilterMode[] {
  if (kind === 'presence') return ['empty', 'not_empty'];
  return [
    ...(kind === 'text' ? (['contains', 'not_contains', 'starts_with', 'ends_with'] as const) : []),
    'eq',
    'ne',
    ...(kind === 'number' ? (['gt', 'gte', 'lt', 'lte', 'range'] as const) : []),
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
    return { op: 'range', value: lower.value ?? '', upper: upper.value ?? '' };
  const first = own[0];
  return {
    op: first && !['in', 'not_in', 'band'].includes(first.op) ? (first.op as FilterMode) : fallback,
    value: first?.value ?? '',
    upper: '',
  };
}
export function compileColumnFilter(
  column: string,
  draft: FilterDraft,
  kind: FilterValueKind,
): ColumnFilter[] {
  if (!columnFilterModes(kind).includes(draft.op)) throw new UiError('此列不支持该筛选条件。');
  if (draft.op === 'empty' || draft.op === 'not_empty') return [{ column, op: draft.op }];
  const value = draft.value.trim();
  if (!value) throw new UiError('请输入筛选值。');
  if (Array.from(value).length > 1000) throw new UiError('筛选值不能超过 1000 个字符。');
  const finiteScalar = (text: string) =>
    /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(text) && Number.isFinite(Number(text));
  if (kind === 'number') {
    if (!finiteScalar(value)) throw new UiError('比较条件需要有限数值，不能使用等级或区间文本。');
  }
  if (draft.op === 'range') {
    const upper = draft.upper.trim();
    if (!finiteScalar(upper)) throw new UiError('请输入有效的筛选上限。');
    if (Number(value) > Number(upper)) throw new UiError('筛选下限不能大于上限。');
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
  const next = [...filters.filter((filter) => filter.column !== column), ...replacement];
  if (next.length > 20 || new TextEncoder().encode(JSON.stringify(next)).byteLength > 16 * 1024)
    throw new UiError('筛选条件超过 20 项或 16 KiB 限额，请减少选择。');
  return next;
}
