import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../src/api/errors';
import { useResource } from '../src/hooks/useResource';

const fault = new ApiError(0, 'network_error', 'Controlled network failure');
const options = { recoverGetErrors: true, retainOnError: true };
const poll = { milliseconds: 5000, while: () => true };
beforeEach(() => vi.useFakeTimers());

async function advance(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

it('recovers an initial read after the bounded delay, without inventing initial data', async () => {
  const read = vi.fn(async (_signal: AbortSignal) => 'current').mockRejectedValueOnce(fault);
  const { result } = renderHook(() => useResource('source', read, undefined, options));
  await advance(0);
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBe(fault);
  await advance(999);
  expect(read).toHaveBeenCalledOnce();
  await advance(1);
  expect(read).toHaveBeenCalledTimes(2);
  expect(result.current.data).toBe('current');
  expect(result.current.error).toBeNull();
});

it('exhausts three consecutive recovery reads and permits an explicit fresh check', async () => {
  const read = vi.fn<(_signal: AbortSignal) => Promise<string>>().mockRejectedValue(fault);
  const { result } = renderHook(() => useResource('source', read, poll, options));
  await advance(0);
  expect(read).toHaveBeenCalledOnce();
  await advance(1000);
  expect(read).toHaveBeenCalledTimes(2);
  await advance(2999);
  expect(read).toHaveBeenCalledTimes(2);
  await advance(1);
  expect(read).toHaveBeenCalledTimes(3);
  await advance(7000);
  expect(read).toHaveBeenCalledTimes(4);
  await advance(60000);
  expect(read).toHaveBeenCalledTimes(4);
  expect(result.current.loading).toBe(false);
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBe(fault);
  read.mockResolvedValue('current');
  act(() => result.current.reload());
  await advance(0);
  expect(read).toHaveBeenCalledTimes(5);
  expect(result.current.data).toBe('current');
  expect(result.current.error).toBeNull();
});

it('retains the read fault and last observation while one recovery request is pending', async () => {
  let resolve!: (value: string) => void;
  const read = vi
    .fn<(_signal: AbortSignal) => Promise<string>>()
    .mockResolvedValueOnce('last observed')
    .mockRejectedValueOnce(fault)
    .mockImplementationOnce(() => new Promise((done) => (resolve = done)));
  const { result } = renderHook(() => useResource('source', read, poll, options));
  await advance(0);
  await advance(5000);
  await advance(1000);
  expect(result.current.loading).toBe(true);
  expect(result.current.error).toBe(fault);
  expect(result.current.data).toBe('last observed');
  await advance(60000);
  expect(read).toHaveBeenCalledTimes(3);
  await act(async () => resolve('current'));
  expect(result.current.loading).toBe(false);
  expect(result.current.data).toBe('current');
  expect(result.current.error).toBeNull();
});

it('leaves ordinary manual reads unchanged even when they have a polling predicate', async () => {
  const read = vi.fn<(_signal: AbortSignal) => Promise<string>>().mockRejectedValue(fault);
  const { result } = renderHook(() => useResource('manual', read, poll));
  await advance(60000);
  expect(read).toHaveBeenCalledOnce();
  expect(result.current.error).toBe(fault);
});

it('stops polling when recovery discovers the actual terminal state', async () => {
  const read = vi
    .fn<(_signal: AbortSignal) => Promise<string>>()
    .mockResolvedValueOnce('running')
    .mockRejectedValueOnce(fault)
    .mockResolvedValue('complete');
  const whileRunning = { milliseconds: 5000, while: (value: string) => value === 'running' };
  const { result } = renderHook(() => useResource('source', read, whileRunning, options));
  await advance(0);
  await advance(5000);
  await advance(1000);
  await advance(60000);
  expect(read).toHaveBeenCalledTimes(3);
  expect(result.current.data).toBe('complete');
});

it('resets the consecutive-failure budget only after a successful observation', async () => {
  const read = vi
    .fn<(_signal: AbortSignal) => Promise<string>>()
    .mockRejectedValueOnce(fault)
    .mockRejectedValueOnce(fault)
    .mockRejectedValueOnce(fault)
    .mockResolvedValueOnce('first current')
    .mockRejectedValueOnce(fault)
    .mockResolvedValue('second current');
  const { result } = renderHook(() => useResource('source', read, poll, options));
  await advance(11000);
  expect(read).toHaveBeenCalledTimes(4);
  expect(result.current.data).toBe('first current');
  await advance(5000);
  expect(result.current.error).toBe(fault);
  await advance(1000);
  expect(read).toHaveBeenCalledTimes(6);
  expect(result.current.data).toBe('second current');
});
