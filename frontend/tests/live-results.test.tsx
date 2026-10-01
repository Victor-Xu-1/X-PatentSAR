import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { Job } from '../src/api/types';
import { useResultsState } from '../src/features/workspace/useResultsState';
import { job, project, results } from './fixtures';

describe('current-run result ownership and stage synchronization', () => {
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
        stages: job.stages.map((stage) =>
          stage.name === 'classify' ? { ...stage, status: 'ok', count: 369 } : stage,
        ),
      },
    });
    await waitFor(() => expect(reloadProject).toHaveBeenCalledTimes(1));
  });
});
