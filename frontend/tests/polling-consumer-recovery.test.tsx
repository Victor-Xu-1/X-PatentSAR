import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { useEnvironmentWorkspace } from '../src/features/environment/useEnvironmentWorkspace';
import { useSARResource } from '../src/features/sar/useSARResource';
import { isActiveJob } from '../src/features/sar/presentation';
import { environmentCatalog, environmentOperation } from './environment-fixtures';
import { sarJob } from './sar-fixtures';

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new Error('No network is permitted in this controlled regression');
    }),
  );
});

async function advance(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

it('recovers a polled SAR job without validating its retained stale snapshot', async () => {
  const running = { ...sarJob, status: 'running' as const, finished_at: null };
  const load = vi.fn(async (_signal: AbortSignal) => running);
  const poll = { milliseconds: 2000, while: isActiveJob };
  const { result, unmount } = renderHook(() =>
    useSARResource('controlled-sar-job', true, load, poll),
  );
  try {
    await advance(0);
    expect(result.current.validated).toBe(true);
    const fault = new ApiError(503, 'http_error', 'Temporary service fault');
    load.mockRejectedValueOnce(fault);
    await advance(2000);
    expect(result.current.error).toBe(fault);
    expect(result.current.data?.id).toBe(running.id);
    expect(result.current.validated).toBe(false);
    await advance(1000);
    expect(result.current.validated).toBe(true);
    expect(load).toHaveBeenCalledTimes(3);
    expect(fetch).not.toHaveBeenCalled();
  } finally {
    unmount();
  }
});

it('recovers environment progress reads without launching or cancelling an operation', async () => {
  vi.spyOn(api, 'environments').mockResolvedValue(environmentCatalog);
  const read = vi.spyOn(api, 'environmentOperation').mockResolvedValue(environmentOperation);
  const start = vi
    .spyOn(api, 'createEnvironmentOperation')
    .mockRejectedValue(new Error('No writes'));
  const cancel = vi
    .spyOn(api, 'cancelEnvironmentOperation')
    .mockRejectedValue(new Error('No writes'));
  const choose = vi.fn();
  const { result, unmount } = renderHook(() =>
    useEnvironmentWorkspace(environmentOperation.id, choose),
  );
  try {
    await advance(0);
    expect(result.current.operation.data?.id).toBe(environmentOperation.id);
    const fault = new ApiError(0, 'timeout', 'Temporary read timeout');
    read.mockRejectedValueOnce(fault);
    await advance(1500);
    expect(result.current.operation.error).toBe(fault);
    expect(result.current.selected?.id).toBe(environmentOperation.id);
    await advance(1000);
    expect(read).toHaveBeenCalledTimes(3);
    expect(result.current.operation.error).toBeNull();
    expect(result.current.operation.data?.id).toBe(environmentOperation.id);
    expect(start).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
    expect(choose).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  } finally {
    unmount();
  }
});
