import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Job } from '../src/api/types';
import { useResultsState } from '../src/features/workspace/useResultsState';
import { compound, job, project, results } from './fixtures';

describe('current-run result ownership and stage synchronization', () => {
  it('does not refresh current results from an unavailable shared-directory stage history', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    const reloadProject = vi.fn();
    const unknown: Job = { ...job, history_available: false };
    const { rerender } = renderHook(
      ({ current }) => useResultsState(project.id, '', vi.fn(), current, reloadProject),
      { initialProps: { current: unknown } },
    );
    await waitFor(() => expect(reloadProject).toHaveBeenCalled());
    reloadProject.mockClear();
    rerender({
      current: {
        ...unknown,
        stages: unknown.stages.map((stage) => ({ ...stage, status: 'ok' as const, count: 99 })),
      },
    });
    expect(reloadProject).not.toHaveBeenCalled();
  });
  it('refreshes project and result evidence when a new active run replaces a failed run', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    const reloadProject = vi.fn();
    const onQuery = vi.fn();
    const previous: Job = { ...job, id: 'previous', status: 'failed' };
    const { rerender } = renderHook(
      ({ current }) => useResultsState(project.id, '', onQuery, current, reloadProject),
      { initialProps: { current: previous } },
    );
    await waitFor(() => expect(reloadProject).toHaveBeenCalled());
    reloadProject.mockClear();
    rerender({ current: { ...job, id: 'fresh' } });
    await waitFor(() => expect(reloadProject).toHaveBeenCalledTimes(1));
  });

  it('refreshes only when persisted stage facts change, not on every status poll', async () => {
    vi.spyOn(api, 'results').mockResolvedValue(results);
    const reloadProject = vi.fn();
    const onQuery = vi.fn();
    const { rerender } = renderHook(
      ({ current }) => useResultsState(project.id, '', onQuery, current, reloadProject),
      { initialProps: { current: job } },
    );
    await waitFor(() => expect(reloadProject).toHaveBeenCalled());
    reloadProject.mockClear();
    rerender({
      current: { ...job, stages: job.stages.map((stage) => ({ ...stage, duration_seconds: 12 })) },
    });
    expect(reloadProject).not.toHaveBeenCalled();
    rerender({
      current: {
        ...job,
        stages: job.stages.map((stage) => ({
          ...stage,
          progress: {
            completed: 12,
            total: 100,
            cache_hits: 3,
            failures: 0,
            device: 'cpu' as const,
            peak_rss_mb: 256,
          },
        })),
      },
    });
    expect(reloadProject).not.toHaveBeenCalled();
    rerender({
      current: {
        ...job,
        stages: job.stages.map((stage) =>
          stage.name === 'classify' ? { ...stage, status: 'ok', count: 369 } : stage,
        ),
      },
    });
    await waitFor(() => expect(reloadProject).toHaveBeenCalledTimes(1));
  });

  it('refreshes existing rows on a phase transition and terminal state, not recognition counter ticks', async () => {
    let data = results;
    const read = vi.spyOn(api, 'results').mockImplementation(async () => data);
    const reloadProject = vi.fn();
    const current: Job = {
      ...job,
      include_admet: true,
      admet_only: true,
      stages: [],
      admet_stage: {
        name: 'admet',
        status: 'running',
        count: 0,
        duration_seconds: 1,
        reused_checkpoint: false,
        progress: {
          phase: 'recognition',
          completed: 1,
          total: 7,
          cache_hits: 1,
          failures: 0,
          device: 'cpu',
          peak_rss_mb: null,
        },
      },
    };
    const { result, rerender } = renderHook(
      ({ current }) => useResultsState(project.id, '', vi.fn(), current, reloadProject),
      { initialProps: { current } },
    );
    await waitFor(() => expect(result.current.resource.data).toBe(results));
    read.mockClear();
    reloadProject.mockClear();
    rerender({
      current: {
        ...current,
        admet_stage: {
          ...current.admet_stage!,
          duration_seconds: 12,
          progress: { ...current.admet_stage!.progress!, completed: 2 },
        },
      },
    });
    expect(read).not.toHaveBeenCalled();
    expect(reloadProject).not.toHaveBeenCalled();

    data = { ...results, items: [{ ...compound, smiles: 'CCO' }] };
    const properties: Job = {
      ...current,
      admet_stage: {
        ...current.admet_stage!,
        progress: {
          ...current.admet_stage!.progress!,
          phase: 'properties',
          completed: 0,
          total: 1,
          cache_hits: 0,
        },
      },
    };
    rerender({ current: properties });
    await waitFor(() => expect(result.current.resource.data?.items[0]?.smiles).toBe('CCO'));
    expect(read).toHaveBeenCalledOnce();
    expect(reloadProject).toHaveBeenCalledOnce();
    read.mockClear();
    reloadProject.mockClear();

    rerender({ current: { ...properties, status: 'complete' } });
    await waitFor(() => expect(read).toHaveBeenCalledOnce());
    expect(reloadProject).toHaveBeenCalledOnce();
  });
});
