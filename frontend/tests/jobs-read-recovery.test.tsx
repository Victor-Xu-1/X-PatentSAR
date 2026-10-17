import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { useJobs } from '../src/features/jobs/useJobs';
import { job, project } from './fixtures';

afterEach(() => vi.useRealTimers());

it.each(['list', 'detail'] as const)(
  'recovers a transient %s read without replaying task mutations',
  async (failedRead) => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () => {
      throw new Error('No network is permitted in this controlled regression');
    });
    vi.stubGlobal('fetch', fetch);
    const create = vi.spyOn(api, 'createJob').mockRejectedValue(new Error('Unexpected task write'));
    const cancel = vi.spyOn(api, 'cancelJob').mockRejectedValue(new Error('Unexpected task write'));
    const listing = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
    const detail = vi.spyOn(api, 'job').mockResolvedValue(job);
    const { result, unmount } = renderHook(() => useJobs(project.id));

    try {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.verified).toBe(true);
      expect(result.current.job?.id).toBe(job.id);

      const fault = new ApiError(0, 'network_error', 'Temporary task read failure');
      if (failedRead === 'list') listing.mockRejectedValueOnce(fault);
      else detail.mockRejectedValueOnce(fault);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(failedRead === 'list' ? 5000 : 3000);
      });
      expect(failedRead === 'list' ? result.current.error : result.current.detailError).toBe(fault);
      expect(result.current.job?.id).toBe(job.id);
      expect(result.current.verified).toBe(false);

      // A later bounded read must recover the same running task without a
      // manual reload, task restart, cancellation or real HTTP request.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000);
      });
      expect(create).not.toHaveBeenCalled();
      expect(cancel).not.toHaveBeenCalled();
      expect(fetch).not.toHaveBeenCalled();
      expect((failedRead === 'list' ? listing : detail).mock.calls.length).toBeGreaterThanOrEqual(
        3,
      );
      expect(result.current.verified).toBe(true);
      expect(result.current.job?.id).toBe(job.id);
      expect(result.current.error).toBeNull();
      expect(result.current.detailError).toBeNull();
    } finally {
      unmount();
    }
  },
);
