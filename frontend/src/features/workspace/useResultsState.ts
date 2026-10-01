import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { Filters, Job } from '../../api/types';
import { useDebounced } from '../../hooks/useDebounced';
import { useResource } from '../../hooks/useResource';
import { observedStages } from '../../model/extraction';

export function useResultsState(
  id: string | null,
  query: string,
  onQuery: (query: string) => void,
  job: Job | null,
  onProjectReload: () => void,
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
  if (previousQuery !== query) {
    setPreviousQuery(query);
    setBaseFilters((old) => ({ ...old, page: 1 }));
    setSelected(new Set());
  }
  const debouncedQuery = useDebounced(query);
  const filters: Filters = { ...baseFilters, q: debouncedQuery };
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
        observedStages(job).map(({ name, status, count }) => [name, status, count]),
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
    const { q: _query, ...rest } = patch;
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
    }
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
