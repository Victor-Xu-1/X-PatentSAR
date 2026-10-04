import type { ColumnFilter, Filters } from '../api/types';
import { activityBands, columnFilterOperations } from '../api/types';
import type { Route } from './route';

export type TableQuery = Pick<
  Filters,
  'column_filters' | 'sort_column' | 'sort_direction' | 'sort_band'
>;
const maxFilterBytes = 16 * 1024;

function boundedString(value: unknown, max: number, min = 0): value is string {
  if (typeof value !== 'string' || value.length > max * 2) return false;
  // Backend string limits count Unicode code points, not UTF-16 code units.
  const length = Array.from(value).length;
  return length >= min && length <= max;
}

function isFilter(value: unknown): value is ColumnFilter {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const filter = value as Record<string, unknown>;
  if (
    !boundedString(filter.column, 100, 1) ||
    typeof filter.op !== 'string' ||
    !columnFilterOperations.some((op) => op === filter.op) ||
    (filter.include_empty !== undefined && typeof filter.include_empty !== 'boolean') ||
    (filter.value !== undefined && !boundedString(filter.value, 1000)) ||
    (filter.values !== undefined &&
      (!Array.isArray(filter.values) ||
        filter.values.length > 200 ||
        !filter.values.every((item) => boundedString(item, 1000))))
  )
    return false;
  if (filter.op === 'in' || filter.op === 'not_in') return Array.isArray(filter.values);
  if (filter.include_empty !== undefined) return false;
  if (filter.op === 'band') return activityBands.some((band) => band === filter.value);
  if (filter.op === 'empty' || filter.op === 'not_empty') return true;
  return boundedString(filter.value, 1000);
}

export function readTableQuery(params: URLSearchParams): TableQuery | undefined {
  const query: TableQuery = {};
  const raw = params.get('column_filters');
  if (
    raw &&
    raw.length <= maxFilterBytes &&
    new TextEncoder().encode(raw).byteLength <= maxFilterBytes
  ) {
    try {
      const filters: unknown = JSON.parse(raw);
      if (
        Array.isArray(filters) &&
        filters.length <= 20 &&
        filters.every(isFilter) &&
        filters.length
      )
        query.column_filters = filters;
    } catch {
      /* Malformed URL state is not an executable query. */
    }
  }
  const column = params.get('sort_column');
  const direction = params.get('sort_direction') ?? 'asc';
  if (boundedString(column, 100, 1) && (direction === 'asc' || direction === 'desc')) {
    // Known-column and operator ownership stays with the server, not a page-local catalog.
    query.sort_column = column;
    query.sort_direction = direction;
    const band = params.get('sort_band');
    if (column.startsWith('activity:') && activityBands.some((value) => value === band))
      query.sort_band = band as NonNullable<Filters['sort_band']>;
  }
  return Object.keys(query).length ? query : undefined;
}

export function writeTableQuery(params: URLSearchParams, query: TableQuery | undefined): void {
  if (query?.column_filters?.length)
    params.set('column_filters', JSON.stringify(query.column_filters));
  if (query?.sort_column) {
    params.set('sort_column', query.sort_column);
    params.set('sort_direction', query.sort_direction ?? 'asc');
    if (query.sort_band) params.set('sort_band', query.sort_band);
  }
}

export function withTableQuery(route: Route, filters: Filters): Route {
  const next = { ...route };
  delete next.tableQuery;
  if (next.view !== 'workspace' || !next.projectId) return next;
  const query: TableQuery = {};
  if (filters.column_filters?.length) query.column_filters = filters.column_filters;
  if (filters.sort_column) {
    query.sort_column = filters.sort_column;
    query.sort_direction = filters.sort_direction ?? 'asc';
    if (filters.sort_band) query.sort_band = filters.sort_band;
  }
  if (Object.keys(query).length) next.tableQuery = query;
  return next;
}
