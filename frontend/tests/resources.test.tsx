import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useResource } from '../src/hooks/useResource';

describe('resource cancellation and error lifecycle', () => {
  it('aborts a stale read and discards its late result', async () => {
    let resolveFirst!: (value: string) => void;
    let firstSignal!: AbortSignal;
    const first = (signal: AbortSignal) => {
      firstSignal = signal;
      return new Promise<string>((resolve) => {
        resolveFirst = resolve;
      });
    };
    const second = async () => 'second';
    const { result, rerender } = renderHook(({ key, load }) => useResource(key, load), {
      initialProps: { key: 'first', load: first },
    });
    rerender({ key: 'second', load: second });
    expect(firstSignal.aborted).toBe(true);
    await waitFor(() => expect(result.current.data).toBe('second'));
    act(() => resolveFirst('stale'));
    expect(result.current.data).toBe('second');
  });
  it('surfaces failures and only retries when requested', async () => {
    const load = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error('read failed'))
      .mockResolvedValueOnce('recovered');
    const { result } = renderHook(() => useResource('key', load));
    await waitFor(() => expect(result.current.error?.message).toBe('read failed'));
    expect(load).toHaveBeenCalledOnce();
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.data).toBe('recovered'));
    expect(load).toHaveBeenCalledTimes(2);
  });
  it('aborts and releases scheduled work on unmount', async () => {
    let signal!: AbortSignal;
    const load = vi.fn(async (input: AbortSignal) => {
      signal = input;
      return 'loaded';
    });
    const poll = { milliseconds: 1000, while: () => true };
    const { result, unmount } = renderHook(() => useResource('key', load, poll));
    await waitFor(() => expect(result.current.data).toBe('loaded'));
    unmount();
    expect(signal.aborted).toBe(true);
    expect(load).toHaveBeenCalledOnce();
  });
});
