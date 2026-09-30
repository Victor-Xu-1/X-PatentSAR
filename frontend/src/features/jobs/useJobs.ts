import { useCallback } from 'react';
import { api } from '../../api';
import type { Job } from '../../api/types';
import { activeJob } from '../../model/presentation';
import { useResource } from '../../hooks/useResource';

const pollList = (value: { items: Job[] }) => value.items.some(activeJob);
export function useJobs(projectId: string | null, enabled = true) {
  const load = useCallback((signal: AbortSignal) => api.jobs(projectId, signal), [projectId]);
  const list = useResource(enabled ? `jobs:${projectId ?? 'all'}` : null, load, {
    milliseconds: 5000,
    while: pollList,
  });
  const latest = list.data
    ? ([...list.data.items].sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null)
    : null;
  const id = latest?.id ?? null;
  const loadJob = useCallback((signal: AbortSignal) => api.job(id ?? '', signal), [id]);
  const detail = useResource(id ? `job:${id}` : null, loadJob, {
    milliseconds: 3000,
    while: activeJob,
  });
  const reloadList = list.reload;
  const reloadDetail = detail.reload;
  const reload = useCallback(() => {
    reloadList();
    reloadDetail();
  }, [reloadList, reloadDetail]);
  return { ...list, reload, job: detail.data ?? latest, detailError: detail.error };
}
