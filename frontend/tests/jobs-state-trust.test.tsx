import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { useJobs } from '../src/features/jobs/useJobs';
import { JobActions } from '../src/features/jobs/JobActions';
import { StageStrip } from '../src/features/jobs/StageStrip';
import { setLocale } from '../src/i18n';
import userEvent from '@testing-library/user-event';
import { job, project } from './fixtures';

beforeEach(() => setLocale('en'));

it('marks retained task details as unknown while preserving the source identifier', async () => {
  render(
    <JobActions project={project} job={job} ready verified={false} onChange={vi.fn()} compact />,
  );
  await userEvent.click(screen.getByRole('button', { name: 'Task details' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveTextContent('Stage status unknown');
  expect(dialog).toHaveTextContent(job.id);
});

it('unknown initial task state cannot be interpreted as permission to run', () => {
  const create = vi.spyOn(api, 'createJob');
  render(
    <>
      <StageStrip job={null} verified={false} compact />
      <JobActions project={project} job={null} ready verified={false} onChange={vi.fn()} compact />
    </>,
  );
  expect(screen.getByRole('button', { name: 'Run extraction' })).toBeDisabled();
  expect(screen.queryByText('Not started')).not.toBeInTheDocument();
  expect(screen.getAllByText('Stage status unknown').some((item) => item.closest('summary'))).toBe(
    true,
  );
  expect(create).not.toHaveBeenCalled();
});

it('unverified last-known state cannot cancel, resume or start a task', () => {
  const { rerender } = render(
    <JobActions project={project} job={job} ready verified={false} onChange={vi.fn()} compact />,
  );
  expect(screen.getByRole('button', { name: 'Cancel task' })).toBeDisabled();
  rerender(
    <JobActions
      project={project}
      job={{ ...job, status: 'failed', can_resume: true }}
      ready
      verified={false}
      onChange={vi.fn()}
      compact
    />,
  );
  expect(screen.getByRole('button', { name: 'Resume extraction' })).toBeDisabled();
  rerender(<JobActions project={project} job={job} ready verified onChange={vi.fn()} compact />);
  expect(screen.getByRole('button', { name: 'Cancel task' })).toBeEnabled();
});

it('retains the same-source running job on read failure, blocks actions and recovers on explicit retry', async () => {
  const listing = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
  vi.spyOn(api, 'job').mockResolvedValue(job);
  const { result } = renderHook(() => useJobs(project.id));
  await waitFor(() => expect(result.current.verified).toBe(true));
  listing.mockRejectedValueOnce(new Error('source read failed'));
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.error?.message).toBe('source read failed'));
  expect(result.current.job?.id).toBe(job.id);
  expect(result.current.verified).toBe(false);
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.verified).toBe(true));
  expect(result.current.job?.id).toBe(job.id);
});

it('does not transport retained job state across a project change', async () => {
  vi.spyOn(api, 'jobs').mockImplementation(async (id) => ({
    items: id === project.id ? [job] : [],
  }));
  vi.spyOn(api, 'job').mockResolvedValue(job);
  const { result, rerender } = renderHook(({ id }) => useJobs(id), {
    initialProps: { id: project.id },
  });
  await waitFor(() => expect(result.current.job?.id).toBe(job.id));
  rerender({ id: 'another-project' });
  await waitFor(() => expect(result.current.verified).toBe(true));
  expect(result.current.job).toBeNull();
});
