import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { FilterValues } from '../src/api/types';
import { useFilterValues } from '../src/features/results/useFilterValues';
import { filterValuesFixture } from './filter-value-fixtures';

const filters = { q: '', confidence: '', review: '', target: '', page: 1, page_size: 25 };
function deferred() {
  let resolve!: (value: FilterValues) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<FilterValues>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

describe('one abortable, debounced choice request per open menu', () => {
  it('aborts before a new search, ignores late success/failure, and cancels on close', async () => {
    vi.useFakeTimers();
    const pending = [deferred(), deferred(), deferred()];
    const signals: AbortSignal[] = [];
    let ongoing = 0;
    let peak = 0;
    const read = vi
      .spyOn(api, 'filterValues')
      .mockImplementation((_id, _column, _filters, _search, _page, signal) => {
        const item = pending[signals.length]!;
        signals.push(signal);
        ongoing++;
        peak = Math.max(peak, ongoing);
        signal.addEventListener(
          'abort',
          () => {
            ongoing--;
          },
          { once: true },
        );
        return item.promise;
      });
    const { result, rerender, unmount } = renderHook(
      ({ search }) => useFilterValues('id', 'compound', filters, search, 1),
      { initialProps: { search: '' } },
    );
    expect(result.current.loading).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(read).toHaveBeenCalledTimes(1);
    rerender({ search: 'a' });
    expect(signals[0]!.aborted).toBe(true);
    rerender({ search: 'ab' });
    await act(() => vi.advanceTimersByTimeAsync(249));
    expect(read).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(read).toHaveBeenCalledTimes(2);
    await act(async () => pending[0]!.resolve(filterValuesFixture('compound', ['STALE'])));
    expect(result.current.data).toBeNull();
    rerender({ search: 'abc' });
    expect(signals[1]!.aborted).toBe(true);
    await act(async () => pending[1]!.reject(new Error('late stale failure')));
    expect(result.current.error).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(250));
    expect(peak).toBe(1);
    unmount();
    expect(signals[2]!.aborted).toBe(true);
    expect(ongoing).toBe(0);
  });
  it('retains server dominant number kind during search failure rather than guessing from rank metadata', async () => {
    vi.useFakeTimers();
    const read = vi
      .spyOn(api, 'filterValues')
      .mockResolvedValueOnce(
        filterValuesFixture('activity:opaque', ['<10', '12'], { kind: 'number' }),
      )
      .mockRejectedValueOnce(new Error('search offline'));
    const { result, rerender } = renderHook(
      ({ search }) => useFilterValues('id', 'activity:opaque', filters, search, 1),
      { initialProps: { search: '' } },
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(result.current.kind).toBe('number');
    rerender({ search: '<10' });
    expect(result.current.data).toBeNull();
    expect(result.current.kind).toBe('number');
    await act(() => vi.advanceTimersByTimeAsync(250));
    expect(read).toHaveBeenCalledTimes(2);
    expect(result.current.error?.message).toBe('search offline');
    expect(result.current.kind).toBe('number');
  });
  it('cancels a pending debounce before transport starts', async () => {
    vi.useFakeTimers();
    const read = vi.spyOn(api, 'filterValues');
    const { unmount } = renderHook(() => useFilterValues('id', 'compound', filters, 'A', 1));
    unmount();
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(read).not.toHaveBeenCalled();
  });
});
