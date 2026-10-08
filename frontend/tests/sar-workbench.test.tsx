import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { MoleculeBrowser } from '../src/features/sar/MoleculeBrowser';
import { DeleteDataset } from '../src/features/sar/DeleteDataset';
import { DatasetWorkbench } from '../src/features/sar/DatasetWorkbench';
import { SARFailure } from '../src/features/sar/SARFailure';
import { ApiError } from '../src/api/errors';
import { sarDataset, sarInvalid, sarJob, sarMolecule, studyProfile } from './sar-fixtures';
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  vi.spyOn(sarApi, 'molecules').mockResolvedValue({
    items: [sarMolecule, sarInvalid],
    total: 3,
    page: 1,
    page_size: 50,
  });
  vi.spyOn(sarApi, 'jobs').mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
});
describe('all-row dataset presentation', () => {
  it('localizes safe SAR error fallback but leaves original server details and machine code intact', async () => {
    render(
      <SARFailure
        error={new ApiError(422, 'sar_graph_changed', 'Original identifier 原始/control is stale.')}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('SAR request failed (sar_graph_changed)');
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('alert')).toHaveTextContent('SAR 请求失败（sar_graph_changed）');
    expect(screen.getByText('Original identifier 原始/control is stale.')).toBeInTheDocument();
  });
  it('keeps missing/invalid structures and explicit issues visible, and disables only their reference action', async () => {
    const onReference = vi.fn();
    render(
      <MoleculeBrowser active dataset={sarDataset} referenceId={null} onReference={onReference} />,
    );
    await screen.findByText('原文 missing');
    expect(screen.getByText('missing_smiles')).toBeVisible();
    expect(screen.getByText('graph_conflict')).toBeVisible();
    expect(screen.getByText('SMILES not provided')).toBeVisible();
    const buttons = screen.getAllByRole('button', { name: 'Reference' });
    expect(buttons[0]).toBeEnabled();
    expect(buttons[1]).toBeDisabled();
    await userEvent.click(buttons[0]!);
    expect(onReference).toHaveBeenCalledWith(sarMolecule);
  });
  it('searches server pages without translating source input or invoking chemistry/analysis', async () => {
    const rows = vi.spyOn(sarApi, 'molecules').mockImplementation(async (_id, page, _query) => ({
      items: [sarMolecule],
      total: 55,
      page,
      page_size: 50,
    }));
    render(
      <MoleculeBrowser active dataset={sarDataset} referenceId={null} onReference={vi.fn()} />,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(rows.mock.calls.at(-1)?.[1]).toBe(2));
    await userEvent.type(screen.getByLabelText('Search identifiers or SMILES'), '原文');
    await waitFor(() =>
      expect(rows.mock.calls.at(-1)?.slice(0, 3)).toEqual([sarDataset.id, 1, '原文']),
    );
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('搜索编号或 SMILES')).toHaveValue('原文');
  });
  it('shows original-record and merged-row counts separately without guessing input counts', async () => {
    render(
      <DatasetWorkbench
        active
        datasetId={sarDataset.id}
        jobId={null}
        onJob={vi.fn()}
        onRemoved={vi.fn()}
      />,
    );
    await screen.findByText('4 source records · 3 merged molecule rows');
    await userEvent.click(screen.getByText('Dataset actions'));
    expect(screen.getByText('4 source records · 3 merged molecule rows')).toBeVisible();
    expect(screen.getByText('3 rows · 2 eligible · 1 issues')).toBeVisible();
    await userEvent.click(screen.getByText('Single-reference comparison (advanced)'));
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
  });
});
describe('inactive dataset soft removal', () => {
  it('requires explicit confirmation and a successful current jobs check', async () => {
    const remove = vi.spyOn(sarApi, 'removeDataset').mockResolvedValue(undefined);
    const removed = vi.fn();
    render(<DeleteDataset active dataset={sarDataset} onRemoved={removed} />);
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Remove dataset' }));
    const button = await screen.findByRole('button', { name: 'Confirm soft removal' });
    await waitFor(() => expect(button).toBeEnabled());
    expect(screen.getByText(/no disk space is reclaimed/)).toBeVisible();
    await userEvent.click(button);
    await waitFor(() => expect(removed).toHaveBeenCalledOnce());
    expect(remove).toHaveBeenCalledExactlyOnceWith(sarDataset.id);
  });
  it('blocks active datasets and a failed activity check', async () => {
    vi.spyOn(sarApi, 'jobs').mockResolvedValue({
      items: [{ ...sarJob, status: 'running' }],
      total: 1,
    });
    render(<DeleteDataset active dataset={sarDataset} onRemoved={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove dataset' }));
    await screen.findByText(/Active datasets cannot be removed/);
    expect(screen.getByRole('button', { name: 'Confirm soft removal' })).toBeDisabled();
    vi.spyOn(sarApi, 'jobs').mockRejectedValue(new Error('status unavailable'));
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('status unavailable');
    expect(screen.getByRole('button', { name: 'Confirm soft removal' })).toBeDisabled();
  });
});
