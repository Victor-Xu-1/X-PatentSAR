import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import App from '../src/App';
import { api } from '../src/api';
import { setLocale } from '../src/i18n';
import { JobActions } from '../src/features/jobs/JobActions';
import { useJobs } from '../src/features/jobs/useJobs';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { health, job, project, session, projectListResource } from './fixtures';

beforeEach(() => {
  setLocale('zh-CN');
  window.location.hash = '#/jobs';
  vi.spyOn(api, 'session').mockResolvedValue(session);
  vi.spyOn(api, 'health').mockResolvedValue(health);
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [] });
});

it('retains the latest verified source title if a subsequent metadata read is unknown', async () => {
  const props = { ready: false, onOpen: vi.fn() };
  const view = render(<JobsPage {...props} projects={projectListResource([project])} />);
  const select = screen.getByLabelText('筛选任务所属项目');
  await userEvent.selectOptions(select, project.id);
  const renamed = { ...project, title: 'Updated 原文 title' };
  view.rerender(<JobsPage {...props} projects={projectListResource([renamed])} />);
  expect(select).toHaveDisplayValue(renamed.title);
  view.rerender(
    <JobsPage
      {...props}
      projects={{
        data: null,
        error: new Error('Metadata unavailable'),
        loading: false,
        reload: vi.fn(),
      }}
    />,
  );
  expect(select).toHaveValue(project.id);
  expect(select).toHaveDisplayValue(renamed.title);
});

it('uses task-list records without loading an unused latest-task detail on the history page', async () => {
  const complete = { ...job, status: 'complete' as const };
  vi.spyOn(api, 'projects').mockResolvedValue({ items: [project] });
  vi.mocked(api.jobs).mockResolvedValue({ items: [complete] });
  const detail = vi.spyOn(api, 'job').mockResolvedValue(complete);
  render(<App />);
  await screen.findByText('运行完成');
  expect(detail).not.toHaveBeenCalled();
});

it('retains the default current-detail path used by the workspace', async () => {
  const complete = { ...job, status: 'complete' as const };
  vi.mocked(api.jobs).mockResolvedValue({ items: [complete] });
  const detail = vi.spyOn(api, 'job').mockResolvedValue(complete);
  const view = renderHook(() => useJobs(project.id));
  await waitFor(() => expect(detail).toHaveBeenCalledWith(job.id, expect.any(AbortSignal)));
  await waitFor(() => expect(view.result.current.job).toBe(complete));
});

it('shows project-read failure with explicit retry instead of silently treating it as an empty list', async () => {
  const read = vi
    .spyOn(api, 'projects')
    .mockRejectedValue(new Error('Project metadata unavailable'));
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Project metadata unavailable');
  expect(screen.getByLabelText('筛选任务所属项目')).toBeDisabled();
  read.mockResolvedValue({ items: [project] });
  await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() => expect(screen.getByLabelText('筛选任务所属项目')).toBeEnabled());
  expect(screen.getByRole('option', { name: project.title })).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('refreshes project choices with task records and retains the selected scope through an unknown read and retry', async () => {
  const read = vi.spyOn(api, 'projects').mockResolvedValue({ items: [project] });
  render(<App />);
  const select = await screen.findByLabelText('筛选任务所属项目');
  await screen.findByRole('option', { name: project.title });
  await userEvent.selectOptions(select, project.id);
  await waitFor(() =>
    expect(api.jobs).toHaveBeenLastCalledWith(project.id, expect.any(AbortSignal)),
  );
  const count = read.mock.calls.length;
  read.mockRejectedValue(new Error('Project metadata unavailable'));
  await userEvent.click(screen.getByRole('button', { name: '刷新任务记录' }));
  await waitFor(() => expect(read.mock.calls.length).toBe(count + 1));
  expect(await screen.findByRole('alert')).toHaveTextContent('Project metadata unavailable');
  expect(select).toHaveValue(project.id);
  expect(select).toBeDisabled();
  expect(screen.getByRole('option', { name: project.title })).toBeVisible();
  expect(api.jobs).toHaveBeenLastCalledWith(project.id, expect.any(AbortSignal));
  await act(() => setLocale('en'));
  expect(screen.getByLabelText('Filter tasks by project')).toBe(select);
  expect(select).toHaveValue(project.id);
  expect(screen.getByRole('option', { name: project.title })).toBeVisible();
  await act(() => setLocale('zh-CN'));
  read.mockResolvedValue({ items: [project] });
  await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
  await waitFor(() => expect(select).toBeEnabled());
  expect(select).toHaveValue(project.id);
});

it.each([null, { ...project, id: 'different-project' }])(
  'does not offer cancellation without the matching project identity',
  (linked) => {
    render(
      <JobActions project={linked} job={{ ...job, status: 'running' }} ready onChange={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: '取消任务' })).toBeDisabled();
  },
);

it('retains the chosen project during a pending metadata refresh rather than treating it as a fresh removal', async () => {
  const read = vi.spyOn(api, 'projects').mockResolvedValue({ items: [project] });
  render(<App />);
  await screen.findByRole('option', { name: project.title });
  const select = screen.getByLabelText('筛选任务所属项目');
  await userEvent.selectOptions(select, project.id);
  let resolve!: (value: { items: (typeof project)[] }) => void;
  read.mockReturnValue(
    new Promise((value) => {
      resolve = value;
    }),
  );
  await userEvent.click(screen.getByRole('button', { name: '刷新任务记录' }));
  await waitFor(() => expect(select).toHaveAttribute('aria-busy', 'true'));
  expect(select).toBeDisabled();
  expect(select).toHaveValue(project.id);
  await act(() => resolve({ items: [project] }));
  await waitFor(() => expect(select).toBeEnabled());
  expect(select).toHaveValue(project.id);
});
