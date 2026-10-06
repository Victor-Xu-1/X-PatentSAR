import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { client } from '../src/api';
import type { Job } from '../src/api/types';
import { JobActions } from '../src/features/jobs/JobActions';
import { job, json, project, session } from './fixtures';

const interrupted: Job = {
  ...job,
  status: 'interrupted',
  can_resume: true,
  include_intermediates: true,
  force: true,
  task_note: '保留原任务选项',
  include_admet: true,
};
const resumed: Job = { ...job, id: 'resumed-contract', status: 'queued' };

describe('single authoritative interrupted-job resume action', () => {
  beforeEach(() => client.resetSession());

  it('shows one visible continuation action and sends the existing resume request only once', async () => {
    let respond: ((response: Response) => void) | undefined;
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            respond = resolve;
          }),
      );
    vi.stubGlobal('fetch', transport);
    const onChange = vi.fn();
    const { rerender } = render(
      <JobActions project={project} job={interrupted} ready onChange={onChange} compact />,
    );
    const resume = screen.getByRole('button', { name: '继续提取' });
    expect(resume).toBeVisible();
    expect(resume).toBeEnabled();
    expect(screen.getAllByRole('button', { name: '继续提取' })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: '运行提取' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '取消任务' })).not.toBeInTheDocument();

    fireEvent.click(resume);
    fireEvent.click(resume);
    await waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
    expect(resume).toBeDisabled();
    expect(transport.mock.calls[1]?.[0]).toBe(`/api/v1/projects/${project.id}/jobs`);
    const request = transport.mock.calls[1]?.[1] as RequestInit;
    expect(request.method).toBe('POST');
    expect(JSON.parse(String(request.body))).toEqual({
      allow_partial: false,
      advisory: false,
      resume_job_id: interrupted.id,
    });
    expect(request.headers).toMatchObject({ 'X-CSRF-Token': session.csrf_token });

    respond!(json(resumed));
    await waitFor(() => expect(onChange).toHaveBeenCalledOnce());
    expect(resume).toBeDisabled();
    fireEvent.click(resume);
    expect(transport).toHaveBeenCalledTimes(2);
    rerender(<JobActions project={project} job={resumed} ready onChange={onChange} compact />);
    expect(screen.queryByRole('button', { name: '继续提取' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled();
  });

  it('does not replay an uncertain resume write before an explicit authoritative refresh', async () => {
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockRejectedValueOnce(new TypeError('controlled connection loss'));
    vi.stubGlobal('fetch', transport);
    const onChange = vi.fn();
    const { rerender } = render(
      <JobActions project={project} job={interrupted} ready onChange={onChange} compact />,
    );
    await userEvent.click(screen.getByRole('button', { name: '继续提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('写入结果未知');
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '继续提取' }));
    expect(transport).toHaveBeenCalledTimes(2);

    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    expect(onChange).toHaveBeenCalledOnce();
    expect(transport).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: '继续提取' })).toBeDisabled();
    rerender(
      <JobActions project={project} job={{ ...interrupted }} ready onChange={onChange} compact />,
    );
    expect(screen.getByRole('button', { name: '继续提取' })).toBeEnabled();
    expect(transport).toHaveBeenCalledTimes(2);
  });

  it('keeps a definite server error visible without automatically resubmitting', async () => {
    const transport = vi
      .fn()
      .mockResolvedValueOnce(json(session))
      .mockResolvedValueOnce(
        json({ error: { code: 'resume_busy', message: '任务暂不可恢复' } }, 409),
      );
    vi.stubGlobal('fetch', transport);
    const onChange = vi.fn();
    render(<JobActions project={project} job={interrupted} ready onChange={onChange} compact />);
    await userEvent.click(screen.getByRole('button', { name: '继续提取' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('任务暂不可恢复');
    expect(screen.getByRole('button', { name: '继续提取' })).toBeEnabled();
    expect(transport).toHaveBeenCalledTimes(2);
    expect(onChange).not.toHaveBeenCalled();
  });

  it.each([
    { label: 'runtime not ready', selectedProject: project, ready: false, current: interrupted },
    {
      label: 'original PDF unavailable',
      selectedProject: { ...project, pdf: { ...project.pdf, available: false } },
      ready: true,
      current: interrupted,
    },
    { label: 'missing project', selectedProject: null, ready: true, current: interrupted },
    {
      label: 'foreign project job',
      selectedProject: project,
      ready: true,
      current: { ...interrupted, project_id: 'foreign-project' },
    },
    {
      label: 'already complete job',
      selectedProject: project,
      ready: true,
      current: { ...interrupted, status: 'complete' as const },
    },
  ])('keeps unsafe continuation disabled: $label', ({ selectedProject, ready, current }) => {
    const transport = vi.fn();
    vi.stubGlobal('fetch', transport);
    render(
      <JobActions
        project={selectedProject}
        job={current}
        ready={ready}
        onChange={vi.fn()}
        compact
      />,
    );
    const resume = screen.getByRole('button', { name: '继续提取' });
    expect(resume).toBeDisabled();
    fireEvent.click(resume);
    expect(transport).not.toHaveBeenCalled();
  });

  it.each(['running', 'queued'] as const)('does not resume an active %s job', (status) => {
    const transport = vi.fn();
    vi.stubGlobal('fetch', transport);
    render(
      <JobActions
        project={project}
        job={{ ...interrupted, status }}
        ready
        onChange={vi.fn()}
        compact
      />,
    );
    expect(screen.queryByRole('button', { name: '继续提取' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消任务' })).toBeEnabled();
    expect(transport).not.toHaveBeenCalled();
  });

  it('does not offer resume without the current server capability', () => {
    const transport = vi.fn();
    vi.stubGlobal('fetch', transport);
    render(
      <JobActions
        project={project}
        job={{ ...interrupted, can_resume: false }}
        ready
        onChange={vi.fn()}
        compact
      />,
    );
    expect(screen.queryByRole('button', { name: '继续提取' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '运行提取' })).toBeEnabled();
    expect(transport).not.toHaveBeenCalled();
  });
});
