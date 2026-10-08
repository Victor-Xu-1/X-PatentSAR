import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { setLocale } from '../src/i18n';
import { PairTable } from '../src/features/sar/PairTable';
import { SARResults } from '../src/features/sar/SARResults';
import { sarDataset, sarDrawing, sarJob, sarPair } from './sar-fixtures';
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'job').mockResolvedValue(sarJob);
  vi.spyOn(sarApi, 'pairs').mockResolvedValue({
    items: [sarPair],
    total: 1,
    page: 1,
    page_size: 50,
    job: sarJob,
  });
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
});
describe('truthful reference comparisons', () => {
  it('preserves censored/repeated original values, missing exact-fold and original labels/reasons in both languages', async () => {
    const { container } = render(
      <PairTable
        dataset={sarDataset}
        pairs={{ items: [sarPair], total: 1, page: 1, page_size: 50, job: sarJob }}
        onSource={vi.fn()}
      />,
    );
    expect(screen.getAllByText('<10 nM')).toHaveLength(2);
    expect(screen.getByText('5 nM')).toBeVisible();
    expect(screen.getByRole('cell', { name: 'Indeterminate' })).toBeVisible();
    expect(screen.getByText('Insufficient evidence')).toBeVisible();
    expect(screen.getByText('raw_reason')).toBeVisible();
    expect(screen.getByText('原文 009')).toBeVisible();
    expect(container.querySelector('tbody tr td:nth-child(7)')).toHaveTextContent('—');
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('cell', { name: 'SAR 无法确定' })).toBeVisible();
    expect(screen.getByText('raw_reason')).toBeVisible();
    expect(screen.getAllByText('<10 nM')).toHaveLength(2);
  });
  it('displays exact folds only as supplied, without local scores or direction inference', () => {
    render(
      <PairTable
        dataset={sarDataset}
        pairs={{
          items: [
            {
              ...sarPair,
              comparison: 'better',
              fold_change: 2.5,
              evidence_basis: 'recorded_context',
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
          job: sarJob,
        }}
        onSource={vi.fn()}
      />,
    );
    expect(screen.getByText('2.5')).toBeVisible();
    expect(screen.getByRole('cell', { name: 'Better' })).toBeVisible();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });
  it('labels filters as current-page only and keeps ambiguity/context mismatch/insufficient rows distinct', async () => {
    const pairs = [
      sarPair,
      {
        ...sarPair,
        molecule_id: 'ambiguous',
        label: '原文 ambiguity',
        match_status: 'ambiguous' as const,
      },
      {
        ...sarPair,
        molecule_id: 'context',
        label: '原文 context',
        comparison: 'context_mismatch' as const,
      },
    ];
    render(
      <PairTable
        dataset={sarDataset}
        pairs={{ items: pairs, total: 100, page: 1, page_size: 50, job: sarJob }}
        onSource={vi.fn()}
      />,
    );
    await userEvent.selectOptions(
      screen.getByLabelText('Match filter (current page)'),
      'ambiguous',
    );
    expect(screen.getByText('原文 ambiguity')).toBeVisible();
    expect(screen.queryByText('原文 009')).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Match filter (current page)'), '');
    await userEvent.selectOptions(
      screen.getByLabelText('Comparison filter (current page)'),
      'context_mismatch',
    );
    expect(screen.getByText('原文 context')).toBeVisible();
    expect(screen.getByText(/Export includes all original/)).toBeVisible();
  });
  it('loads source provenance on demand rather than guessing a result page', async () => {
    const source = vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    await screen.findByText('原文 009');
    expect(source).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Reference source details' }));
    expect(await screen.findByRole('link', { name: 'Original page 8' })).toHaveAttribute(
      'href',
      expect.stringContaining('page=8'),
    );
    expect(source.mock.calls[0]?.[1]).toBe('reference/control');
    expect(screen.getByText('source_row')).toBeVisible();
    expect(screen.getByText('raw target')).toBeVisible();
  });
});
describe('scoped job actions and lifecycle', () => {
  it('cancels only the selected SAR job and refreshes persisted state', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue({ ...sarJob, status: 'running', processed: 1 });
    const cancel = vi.spyOn(sarApi, 'cancel').mockResolvedValue({ ...sarJob, status: 'cancelled' });
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel SAR job' }));
    await waitFor(() => expect(cancel).toHaveBeenCalledExactlyOnceWith(sarJob.id, sarDataset.id));
    expect(screen.getByRole('button', { name: 'Export all CSV' })).toBeDisabled();
  });
  it('resumes only by explicit action using the original immutable input digest', async () => {
    const stopped = { ...sarJob, status: 'interrupted' as const };
    vi.spyOn(sarApi, 'job').mockResolvedValue(stopped);
    const resume = vi
      .spyOn(sarApi, 'resume')
      .mockResolvedValue({ ...sarJob, id: 'resumed-control', status: 'queued' });
    const onJob = vi.fn();
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={onJob} />);
    const button = await screen.findByRole('button', { name: 'Resume SAR job' });
    expect(resume).not.toHaveBeenCalled();
    await userEvent.click(button);
    await waitFor(() => expect(onJob).toHaveBeenCalledWith('resumed-control'));
    expect(resume).toHaveBeenCalledExactlyOnceWith(sarJob.id, sarDataset.id, {
      expected_input_sha256: sarJob.input_sha256,
    });
  });
  it('retains stale results for review but disables resume', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue({ ...sarJob, status: 'interrupted', stale: true });
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    expect(await screen.findByRole('button', { name: 'Resume SAR job' })).toBeDisabled();
    expect(screen.getByText(/Results are stale/)).toBeVisible();
    expect(
      screen.getByText('Comparison results are published only after the job completes.'),
    ).toBeVisible();
    expect(sarApi.pairs).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Export all CSV' })).toBeDisabled();
  });
  it('keeps completed stale results explicitly historical without current acceptance', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue({ ...sarJob, stale: true });
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    expect(await screen.findByText('原文 009')).toBeVisible();
    expect(screen.getByText(/Results are stale/)).toBeVisible();
  });
  it('does not request unpublised partial pairs while the selected job is running', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue({ ...sarJob, status: 'running', processed: 1 });
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    await screen.findByRole('button', { name: 'Cancel SAR job' });
    expect(sarApi.pairs).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Export all JSON' })).toBeDisabled();
  });
  it('reads page 2 from the server and exports the actual whole-job bytes', async () => {
    const readPairs = vi
      .spyOn(sarApi, 'pairs')
      .mockImplementation(async (_id, _datasetId, page) => ({
        items: [sarPair],
        total: 55,
        page,
        page_size: 50,
        job: sarJob,
      }));
    const exportJob = vi
      .spyOn(sarApi, 'export')
      .mockResolvedValue(new Blob(['real-controlled-response']));
    const create = vi.fn((_blob: Blob) => 'blob:controlled');
    const revoke = vi.fn();
    vi.stubGlobal(
      'URL',
      class extends URL {
        static createObjectURL = create;
        static revokeObjectURL = revoke;
      },
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(readPairs.mock.calls.at(-1)?.[2]).toBe(2));
    await userEvent.click(screen.getByRole('button', { name: 'Export all CSV' }));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(exportJob.mock.calls[0]?.slice(0, 2)).toEqual([sarJob.id, 'csv']);
    expect(click).toHaveBeenCalledOnce();
    expect(create.mock.calls[0]?.[0]).toBeInstanceOf(Blob);
  });
  it('aborts read work and stops active-job polling when the module is no longer active', async () => {
    vi.useFakeTimers();
    const readJob = vi
      .spyOn(sarApi, 'job')
      .mockResolvedValue({ ...sarJob, status: 'running', processed: 1 });
    const { rerender } = render(
      <SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(readJob).toHaveBeenCalledOnce();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(readJob).toHaveBeenCalledTimes(2);
    const signal = readJob.mock.calls.at(-1)?.[2];
    rerender(<SARResults active={false} dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(readJob).toHaveBeenCalledTimes(2);
  });
  it('renders retryable read errors, not success-shaped placeholders', async () => {
    vi.spyOn(sarApi, 'job').mockRejectedValue(new Error('read blocked'));
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('read blocked');
    expect(screen.queryByRole('button', { name: 'Export all CSV' })).not.toBeInTheDocument();
  });
});
