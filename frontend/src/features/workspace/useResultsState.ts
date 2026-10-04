import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { Filters, Job } from '../../api/types';
import { useDebounced } from '../../hooks/useDebounced';
import { useResource } from '../../hooks/useResource';
import { observedStages } from '../../model/extraction';
import type { TableQuery } from '../../model/tableQueryRoute';

export function useResultsState(
  id: string | null,
  query: string,
  onQuery: (query: string) => void,
  job: Job | null,
  onProjectReload: () => void,
  tableQuery?: TableQuery,
) {
  const [baseFilters, setBaseFilters] = useState({
    confidence: '',
    review: '',
    target: '',
    page: 1,
    page_size: 25,
  });
  const [selected, setSelected] = useState(new Set<string>());
  const [previousQuery, setPreviousQuery] = useState(query);
  const columnFilters = tableQuery?.column_filters ?? [];
  const sortColumn = tableQuery?.sort_column ?? '';
  const sortDirection = sortColumn ? (tableQuery?.sort_direction ?? 'asc') : 'asc';
  const columnKey = JSON.stringify(columnFilters);
  const tableKey = JSON.stringify([columnKey, sortColumn, sortDirection]);
  const [previousTable, setPreviousTable] = useState({ key: tableKey, columns: columnKey });
  if (previousTable.key !== tableKey) {
    setPreviousTable({ key: tableKey, columns: columnKey });
    setBaseFilters((old) => ({ ...old, page: 1 }));
    if (previousTable.columns !== columnKey) setSelected(new Set());
  }
  if (previousQuery !== query) {
    setPreviousQuery(query);
    setBaseFilters((old) => ({ ...old, page: 1 }));
    setSelected(new Set());
  }
  const debouncedQuery = useDebounced(query);
  const filters: Filters = {
    ...baseFilters,
    q: debouncedQuery,
    column_filters: columnFilters,
    sort_column: sortColumn,
    sort_direction: sortDirection,
  };
  const key = JSON.stringify(filters);
  const load = useCallback(
    (signal: AbortSignal) => api.results(id ?? '', JSON.parse(key) as Filters, signal),
    [id, key],
  );
  const resource = useResource(id ? `results:${id}:${job?.id ?? 'none'}:${key}` : null, load);
  const reload = resource.reload;
  const refreshed = useRef<string | null>(null);
  const snapshot = job
    ? JSON.stringify([
        job.id,
        job.status,
        job.history_available,
        // Recognition publishes rows before properties, without another poller.
        observedStages(job).map(({ name, status, count, progress }) => [
          name,
          status,
          count,
          progress?.phase ?? null,
        ]),
      ])
    : null;
  useEffect(() => {
    if (snapshot && refreshed.current !== snapshot) {
      refreshed.current = snapshot;
      reload();
      onProjectReload();
    }
  }, [snapshot, reload, onProjectReload]);
  function changeFilters(patch: Partial<Filters>) {
    if (patch.q !== undefined) onQuery(patch.q);
    // These fields are owned by the route. Keeping them in local state would
    // resurrect an old query after back/forward navigation or a cleared hash.
    const {
      q: _query,
      column_filters: _columns,
      sort_column: _sort,
      sort_direction: _direction,
      ...rest
    } = patch;
    setBaseFilters((old) => ({ ...old, ...rest }));
    if (
      patch.q !== undefined ||
      patch.target !== undefined ||
      patch.confidence !== undefined ||
      patch.review !== undefined
    )
      setSelected(new Set());
  }
  function toggle(id: string) {
    setSelected((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function selectPage(checked: boolean) {
    setSelected((old) => {
      const next = new Set(old);
      resource.data?.items.forEach((row) => {
        if (checked) next.add(row.id);
        else next.delete(row.id);
      });
      return next;
    });
  }
  function locateCompound(compoundId: string) {
    if (!resource.data?.items.some((row) => row.id === compoundId)) {
      onQuery(compoundId);
      setBaseFilters({ confidence: '', review: '', target: '', page: 1, page_size: 25 });
      setSelected(new Set());
      return true;
    }
    return false;
  }
  return {
    resource,
    filters,
    selected,
    changeFilters,
    toggle,
    selectPage,
    locateCompound,
  };
}
