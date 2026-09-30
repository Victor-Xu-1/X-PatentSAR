import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { Filters, Job } from '../../api/types';
import { activeJob } from '../../model/presentation';
import { useDebounced } from '../../hooks/useDebounced';
import { useResource } from '../../hooks/useResource';

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
  const [metric, setMetric] = useState('');
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
  const resource = useResource(id ? `results:${id}:${key}` : null, load);
  const reload = resource.reload;
  const refreshed = useRef<string | null>(null);
  useEffect(() => {
    if (job && !activeJob(job) && refreshed.current !== `${job.id}:${job.status}`) {
      refreshed.current = `${job.id}:${job.status}`;
      reload();
      onProjectReload();
    }
  }, [job, reload, onProjectReload]);
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
    metric,
    setMetric,
    selected,
    changeFilters,
    toggle,
    selectPage,
    locateCompound,
  };
}
