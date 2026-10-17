import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { decodeJob } from '../src/api/decoders';
import { useResource } from '../src/hooks/useResource';
import { job, json, session } from './fixtures';

beforeEach(() => vi.useFakeTimers());

async function advance(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

it('resumes a GET observer after the real client exhausts its transport attempts', async () => {
  let reads = 0;
  const transport = vi.fn<typeof fetch>(async (url) => {
    if (String(url).endsWith('/session')) return json(session);
    return ++reads <= 2
      ? json({ error: { code: 'http_error', message: 'Service unavailable' } }, 503)
      : json(job);
  });
  const client = new ApiClient(transport);
  const load = (signal: AbortSignal) => client.get('/jobs/job-contract', decodeJob, signal);
  const { result } = renderHook(() =>
    useResource('controlled-task', load, undefined, { recoverGetErrors: true }),
  );
  await advance(300);
  expect(reads).toBe(2);
  expect(result.current.error).toMatchObject({ status: 503 });
  expect(result.current.data).toBeNull();
  await advance(1000);
  expect(reads).toBe(3);
  expect(result.current.data?.id).toBe(job.id);
  expect(result.current.error).toBeNull();
  expect(transport.mock.calls.every(([, request]) => request?.method === 'GET')).toBe(true);
});

it('does not add handshake loops after the client exhausts its safe session renewal', async () => {
  const transport = vi.fn<typeof fetch>(async (url) =>
    String(url).endsWith('/session')
      ? json(session)
      : json({ error: { code: 'session_required', message: 'Session unavailable' } }, 401),
  );
  const client = new ApiClient(transport);
  const load = (signal: AbortSignal) => client.get('/jobs/job-contract', decodeJob, signal);
  const { result } = renderHook(() =>
    useResource('controlled-task', load, undefined, { recoverGetErrors: true }),
  );
  await advance(60000);
  expect(transport).toHaveBeenCalledTimes(4);
  expect(result.current.error).toMatchObject({ status: 401, code: 'session_required' });
  expect(result.current.data).toBeNull();
});

it('never replays an uncertain mutation even when a caller incorrectly opts in', async () => {
  const transport = vi.fn<typeof fetch>(async (url) => {
    if (String(url).endsWith('/session')) return json(session);
    throw new TypeError('Controlled wire failure after a write');
  });
  const client = new ApiClient(transport);
  const incorrectlyMarked = (signal: AbortSignal) =>
    client.mutate('/projects/project-contract/jobs', 'POST', {}, decodeJob, { signal });
  const { result } = renderHook(() =>
    useResource('invalid-read-callback', incorrectlyMarked, undefined, { recoverGetErrors: true }),
  );
  await advance(60000);
  expect(result.current.error).toMatchObject({ code: 'network_error', uncertain: true });
  expect(transport.mock.calls.filter(([, request]) => request?.method === 'POST')).toHaveLength(1);
  expect(transport).toHaveBeenCalledTimes(2);
});
