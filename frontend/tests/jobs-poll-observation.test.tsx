import { act, render, renderHook, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { api } from '../src/api';
import { useJobs } from '../src/features/jobs/useJobs';
import { JobActions } from '../src/features/jobs/JobActions';
import { useResource } from '../src/hooks/useResource';
import { setLocale } from '../src/i18n';
import { job, project } from './fixtures';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const poll = { milliseconds: 1000, while: () => true };
beforeEach(() => setLocale('en'));

it('retains a confirmed read only during a normal same-key background poll', async () => {
  vi.useFakeTimers();
  const load = vi.fn<() => Promise<string>>().mockResolvedValue('original');
  const { result, unmount } = renderHook(() => useResource('source', load, poll));
  await act(async () => {});
  expect(result.current.readConfirmed).toBe(true);
  const pending = deferred<string>();
  load.mockReturnValueOnce(pending.promise);
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(result.current.loading).toBe(true);
  expect(result.current.data).toBe('original');
  expect(result.current.readConfirmed).toBe(true);
  await act(() => pending.resolve('updated'));
  expect(result.current.readConfirmed).toBe(true);
  expect(result.current.data).toBe('updated');
  unmount();
});

it('an explicit reload or key change cannot borrow a previous read confirmation', async () => {
  const load = vi.fn<() => Promise<string>>().mockResolvedValue('original');
  const { result, rerender, unmount } = renderHook(({ key }) => useResource(key, load), {
    initialProps: { key: 'first' },
  });
  await act(async () => {});
  expect(result.current.readConfirmed).toBe(true);
  const reloading = deferred<string>();
  load.mockReturnValueOnce(reloading.promise);
  act(() => result.current.reload());
  expect(result.current.readConfirmed).toBe(false);
  await act(() => reloading.resolve('renewed'));
  expect(result.current.readConfirmed).toBe(true);
  const next = deferred<string>();
  load.mockReturnValueOnce(next.promise);
  rerender({ key: 'second' });
  expect(result.current.readConfirmed).toBe(false);
  expect(result.current.data).toBeNull();
  unmount();
  await act(() => next.resolve('late'));
});

it('a rejected read stays unconfirmed throughout recovery until a new reply succeeds', async () => {
  vi.useFakeTimers();
  const load = vi.fn<() => Promise<string>>().mockResolvedValue('original');
  const { result, unmount } = renderHook(() =>
    useResource('source', load, poll, { retainOnError: true }),
  );
  await act(async () => {});
  load.mockRejectedValueOnce(new Error('read failed'));
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(result.current.data).toBe('original');
  expect(result.current.readConfirmed).toBe(false);
  const pending = deferred<string>();
  load.mockReturnValueOnce(pending.promise);
  act(() => result.current.reload());
  expect(result.current.readConfirmed).toBe(false);
  await act(() => pending.resolve('recovered'));
  expect(result.current.readConfirmed).toBe(true);
  unmount();
});

it.each(['list', 'detail'] as const)(
  'keeps the %s poll presentation confirmed without re-enabling task writes',
  async (kind) => {
    vi.useFakeTimers();
    const list = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
    const detail = vi.spyOn(api, 'job').mockResolvedValue(job);
    const create = vi.spyOn(api, 'createJob');
    const cancel = vi.spyOn(api, 'cancelJob');
    const { result, unmount } = renderHook(() => useJobs(project.id));
    await act(async () => {});
    expect(result.current.verified).toBe(true);
    expect(result.current.presentationVerified).toBe(true);
    const pendingList = deferred<{ items: (typeof job)[] }>();
    const pendingDetail = deferred<typeof job>();
    if (kind === 'list') list.mockReturnValueOnce(pendingList.promise);
    else detail.mockReturnValueOnce(pendingDetail.promise);
    await act(() => vi.advanceTimersByTimeAsync(kind === 'list' ? 5000 : 3000));
    expect(result.current.verified).toBe(false);
    expect(result.current.presentationVerified).toBe(true);
    expect(result.current.job?.id).toBe(job.id);
    if (kind === 'list') await act(() => pendingList.resolve({ items: [job] }));
    else await act(() => pendingDetail.resolve(job));
    expect(result.current.verified).toBe(true);
    expect(create).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
    unmount();
  },
);

it('a newly discovered job cannot borrow presentation confirmation from an old detail', async () => {
  vi.useFakeTimers();
  const next = { ...job, id: 'next-task' };
  const list = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
  const detail = vi.spyOn(api, 'job').mockResolvedValue(job);
  const { result, unmount } = renderHook(() => useJobs(project.id));
  await act(async () => {});
  const pending = deferred<typeof job>();
  list.mockResolvedValueOnce({ items: [next] });
  detail.mockImplementation((id) => (id === next.id ? pending.promise : Promise.resolve(job)));
  await act(() => vi.advanceTimersByTimeAsync(5000));
  expect(result.current.job?.id).toBe(next.id);
  expect(result.current.presentationVerified).toBe(false);
  expect(result.current.verified).toBe(false);
  await act(() => pending.resolve(next));
  expect(result.current.presentationVerified).toBe(true);
  unmount();
});

it('shows confirmed progress in details while cancellation remains disabled during a poll', async () => {
  render(
    <JobActions
      project={project}
      job={job}
      ready
      verified={false}
      presentationVerified
      onChange={vi.fn()}
      compact
    />,
  );
  expect(screen.getByRole('button', { name: 'Cancel task' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: 'Task details' }));
  expect(screen.getByRole('dialog')).not.toHaveTextContent('Stage status unknown');
  expect(screen.getByRole('dialog')).toHaveTextContent(job.id);
});
