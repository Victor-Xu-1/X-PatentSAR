import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { ApiError } from '../src/api/errors';
import { DeleteSARJob } from '../src/features/sar/DeleteSARJob';
import { DatasetWorkbench } from '../src/features/sar/DatasetWorkbench';
import { setLocale } from '../src/i18n';
import { sarDataset, sarJob } from './sar-fixtures';

beforeEach(() => {
  setLocale('en');
});
describe('confirmed SAR task soft removal', () => {
  it.each(['queued', 'running'] as const)('has no delete action for active %s work', (status) => {
    const remove = vi.spyOn(sarApi, 'removeJob');
    render(<DeleteSARJob job={{ ...sarJob, status }} title="raw metric" onRemoved={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Remove SAR job' })).not.toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
  });
  it.each(['complete', 'failed', 'cancelled', 'interrupted'] as const)(
    'confirms terminal %s removal and retained bytes before DELETE',
    async (status) => {
      const remove = vi.spyOn(sarApi, 'removeJob').mockResolvedValue(undefined);
      const removed = vi.fn();
      render(<DeleteSARJob job={{ ...sarJob, status }} title="原文 metric" onRemoved={removed} />);
      await userEvent.click(screen.getByRole('button', { name: 'Remove SAR job' }));
      expect(screen.getByRole('dialog')).toHaveTextContent(
        'Dataset, source, result and audit bytes remain',
      );
      expect(screen.getByText('原文 metric')).toBeVisible();
      expect(remove).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
      await waitFor(() => expect(removed).toHaveBeenCalledExactlyOnceWith(sarJob.id));
      expect(remove).toHaveBeenCalledExactlyOnceWith(sarJob.id);
    },
  );
  it('blocks known cleanup-unverified jobs before mutation', () => {
    const remove = vi.spyOn(sarApi, 'removeJob');
    render(
      <DeleteSARJob
        job={{ ...sarJob, error_code: 'sar_process_unverified' }}
        title="raw metric"
        onRemoved={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Remove SAR job' })).toBeDisabled();
    expect(remove).not.toHaveBeenCalled();
  });
  it('keeps a server cleanup rejection blocked with bilingual fallback and no replay', async () => {
    const remove = vi
      .spyOn(sarApi, 'removeJob')
      .mockRejectedValue(
        new ApiError(409, 'sar_process_unverified', 'Verify owned SAR worker cleanup.'),
      );
    const removed = vi.fn();
    render(<DeleteSARJob job={sarJob} title="raw metric" onRemoved={removed} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove SAR job' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Confirm soft removal' })).toBeDisabled(),
    );
    expect(
      screen.getByText('SAR worker cleanup is unverified. This job cannot be removed.'),
    ).toBeVisible();
    await act(() => setLocale('zh-CN'));
    expect(screen.getByText('SAR 进程清理尚未验证，任务不可移除。')).toBeVisible();
    expect(screen.getByText('Verify owned SAR worker cleanup.')).toBeVisible();
    expect(remove).toHaveBeenCalledOnce();
    expect(removed).not.toHaveBeenCalled();
  });
  it('does not replay uncertain removal; the user can close confirmation to inspect read-only history', async () => {
    const remove = vi
      .spyOn(sarApi, 'removeJob')
      .mockRejectedValue(
        new ApiError(
          0,
          'network_error',
          'SAR 写入响应无法确认。请核对服务器状态，勿重复提交。',
          true,
        ),
      );
    const removed = vi.fn();
    render(<DeleteSARJob job={sarJob} title="raw metric" onRemoved={removed} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove SAR job' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Confirm soft removal' })).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: /retry with the same request/ }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(remove).toHaveBeenCalledOnce();
    expect(removed).not.toHaveBeenCalled();
  });
  it('removing the selected job refreshes the list and clears result selection without resume or recreation', async () => {
    vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
    vi.spyOn(sarApi, 'molecules').mockResolvedValue({
      items: [],
      total: 3,
      page: 1,
      page_size: 50,
    });
    let deleted = false;
    const jobs = vi
      .spyOn(sarApi, 'jobs')
      .mockImplementation(async () => ({ items: deleted ? [] : [sarJob], total: deleted ? 0 : 1 }));
    vi.spyOn(sarApi, 'job').mockResolvedValue(sarJob);
    vi.spyOn(sarApi, 'pairs').mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
      job: sarJob,
    });
    const remove = vi.spyOn(sarApi, 'removeJob').mockImplementation(async () => {
      deleted = true;
    });
    const analyse = vi.spyOn(sarApi, 'analyse');
    const resume = vi.spyOn(sarApi, 'resume');
    const onJob = vi.fn();
    render(
      <DatasetWorkbench
        active
        datasetId={sarDataset.id}
        jobId={sarJob.id}
        onJob={onJob}
        onRemoved={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Remove SAR job' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm soft removal' }));
    await waitFor(() => expect(onJob).toHaveBeenCalledExactlyOnceWith(null));
    await waitFor(() => expect(jobs.mock.calls.length).toBeGreaterThan(1));
    expect(remove).toHaveBeenCalledExactlyOnceWith(sarJob.id);
    expect(analyse).not.toHaveBeenCalled();
    expect(resume).not.toHaveBeenCalled();
    expect(screen.getByText('3 rows · 2 eligible · 1 issues')).toBeVisible();
  });
});
