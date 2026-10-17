import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../src/api/errors';
import { useResource } from '../src/hooks/useResource';

const fault = new ApiError(0, 'network_error', 'Controlled network failure');
const options = { recoverGetErrors: true, retainOnError: true };
beforeEach(() => vi.useFakeTimers());

async function advance(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

it('aborts the observer and cancels its pending recovery on unmount', async () => {
  let signal!: AbortSignal;
  const read = vi.fn(async (input: AbortSignal) => {
    signal = input;
    throw fault;
  });
  const { unmount } = renderHook(() => useResource('source', read, undefined, options));
  await advance(0);
  unmount();
  expect(signal.aborted).toBe(true);
  await advance(60000);
  expect(read).toHaveBeenCalledOnce();
});

it.each(['scheduled', 'in-flight'] as const)(
  'does not transport a %s recovery across an observer key change',
  async (stage) => {
    let resolve!: (value: string) => void;
    const oldRead = vi
      .fn<(_signal: AbortSignal) => Promise<string>>()
      .mockRejectedValueOnce(fault)
      .mockImplementation(() => new Promise((done) => (resolve = done)));
    const newRead = vi.fn(async (_signal: AbortSignal) => 'new source');
    const { result, rerender } = renderHook(
      ({ key, read }) => useResource(key, read, undefined, options),
      {
        initialProps: { key: 'old source', read: oldRead },
      },
    );
    await advance(0);
    if (stage === 'in-flight') await advance(1000);
    const oldSignal = oldRead.mock.calls[0]![0];
    rerender({ key: 'new source', read: newRead });
    expect(oldSignal.aborted).toBe(true);
    await advance(0);
    if (stage === 'in-flight') await act(async () => resolve('obsolete source'));
    await advance(60000);
    expect(result.current.data).toBe('new source');
    expect(result.current.error).toBeNull();
    expect(oldRead).toHaveBeenCalledTimes(stage === 'scheduled' ? 1 : 2);
    expect(newRead).toHaveBeenCalledOnce();
  },
);
