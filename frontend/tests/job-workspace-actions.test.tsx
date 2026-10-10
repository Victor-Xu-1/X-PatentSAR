import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { JobActions } from '../src/features/jobs/JobActions';
import { JobsPage } from '../src/features/jobs/JobsPage';
import { setLocale } from '../src/i18n';
import { job, project, projectListResource } from './fixtures';

beforeEach(() => setLocale('en'));

it.each(['complete', 'failed', 'cancelled', 'interrupted', 'queued', 'running'] as const)(
  'opens the linked current workspace without creating/repeating a %s task or requiring models',
  async (status) => {
    const create = vi.spyOn(api, 'createJob');
    const cancel = vi.spyOn(api, 'cancelJob');
    const onOpen = vi.fn();
    render(
      <JobActions
        job={{ ...job, status }}
        project={project}
        ready={false}
        onChange={vi.fn()}
        onOpenWorkspace={onOpen}
      />,
    );
    const open = screen.getByRole('button', { name: 'Open workspace' });
    expect(open).toHaveClass('primary');
    expect(open).toBeEnabled();
    const run = screen.queryByRole('button', { name: 'Run extraction' });
    if (run) {
      expect(run).not.toHaveClass('primary');
      expect(run).toBeDisabled();
    }
    await userEvent.click(open);
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(project.id);
    expect(create).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();
  },
);

it('passes the existing project navigation from task records and retains source identity across languages', async () => {
  vi.spyOn(api, 'jobs').mockResolvedValue({ items: [{ ...job, status: 'complete' }] });
  const onOpen = vi.fn();
  render(<JobsPage projects={projectListResource([project])} ready={false} onOpen={onOpen} />);
  const opener = await screen.findByRole('button', { name: 'Open workspace' });
  expect(screen.getByRole('button', { name: project.title })).toBeVisible();
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('button', { name: '打开工作台' })).toBe(opener);
  await userEvent.click(opener);
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(project.id);
});

it.each([null, { ...project, id: 'different-project' }])(
  'does not invent a linked workspace when project identity is missing or mismatched',
  (linked) => {
    render(
      <JobActions
        project={linked}
        job={job}
        ready={false}
        onChange={vi.fn()}
        onOpenWorkspace={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Open workspace' })).not.toBeInTheDocument();
  },
);

it('preserves compact workspace controls rather than creating a competing navigation action', () => {
  render(
    <JobActions
      project={project}
      job={{ ...job, status: 'complete' }}
      ready
      onChange={vi.fn()}
      onOpenWorkspace={vi.fn()}
      compact
    />,
  );
  expect(screen.queryByRole('button', { name: 'Open workspace' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Run extraction' })).toHaveClass('primary');
  expect(screen.getByRole('button', { name: 'Run extraction' })).toHaveAttribute(
    'title',
    'Create a new extraction task',
  );
});
