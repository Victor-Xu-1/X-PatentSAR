import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { ApiError } from '../src/api/errors';
import { PredictionAction } from '../src/features/results/PredictionAction';
import { job, project } from './fixtures';

describe('existing-project structure and property completion action', () => {
  it('queues the existing ADMET-only job once and describes completion without a PDF rerun', async () => {
    const create = vi.spyOn(api, 'createJob').mockResolvedValue(job);
    const queued = vi.fn();
    render(<PredictionAction projectId={project.id} disabled={false} onQueued={queued} />);
    fireEvent.click(screen.getByRole('button', { name: '补齐结构与指标' }));
    await waitFor(() => expect(queued).toHaveBeenCalledOnce());
    expect(create).toHaveBeenCalledExactlyOnceWith(project.id, null, {
      include_admet: true,
      admet_only: true,
    });
    expect(screen.getByText(/已提交结构与指标补齐任务.*不重新提取 PDF/)).toBeVisible();
    expect(screen.queryByRole('button', { name: '补齐六项指标' })).not.toBeInTheDocument();
  });

  it('retains the existing disabled gate and prevents duplicate in-flight submission', async () => {
    let finish!: (value: typeof job) => void;
    const create = vi.spyOn(api, 'createJob').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const queued = vi.fn();
    const { rerender } = render(
      <PredictionAction projectId={project.id} disabled onQueued={queued} />,
    );
    const button = screen.getByRole('button', { name: '补齐结构与指标' });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(create).not.toHaveBeenCalled();
    rerender(<PredictionAction projectId={project.id} disabled={false} onQueued={queued} />);
    fireEvent.click(button);
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(create).toHaveBeenCalledOnce();
    await act(async () => finish(job));
    expect(queued).toHaveBeenCalledOnce();
  });

  it('retains uncertain-write recovery without silently re-enqueueing the job', async () => {
    const create = vi
      .spyOn(api, 'createJob')
      .mockRejectedValue(new ApiError(0, 'network_error', '提交结果未知', true));
    const read = vi.spyOn(api, 'jobs').mockResolvedValue({ items: [job] });
    const queued = vi.fn();
    render(<PredictionAction projectId={project.id} disabled={false} onQueued={queued} />);
    fireEvent.click(screen.getByRole('button', { name: '补齐结构与指标' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('提交结果未知');
    expect(screen.getByRole('button', { name: '补齐结构与指标' })).toBeDisabled();
    expect(queued).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '检查已提交任务' }));
    await waitFor(() => expect(queued).toHaveBeenCalledOnce());
    expect(read).toHaveBeenCalledExactlyOnceWith(project.id, expect.any(AbortSignal));
    expect(create).toHaveBeenCalledOnce();
    expect(screen.getByText('此项目已有任务，请查看上方实际进度。')).toBeVisible();
  });
});
