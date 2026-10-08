import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { DatasetWorkbench } from '../src/features/sar/DatasetWorkbench';
import { SARResults } from '../src/features/sar/SARResults';
import { setLocale } from '../src/i18n';
import {
  sarDataset,
  sarDrawing,
  sarInvalid,
  sarJob,
  sarMolecule,
  sarPair,
  sarRegion,
} from './sar-fixtures';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'dataset').mockResolvedValue(sarDataset);
  vi.spyOn(sarApi, 'jobs').mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(sarApi, 'molecules').mockResolvedValue({
    items: [sarMolecule],
    total: 1,
    page: 1,
    page_size: 50,
  });
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
  vi.spyOn(sarApi, 'saveRegion').mockResolvedValue(sarRegion);
  vi.spyOn(sarApi, 'analyse').mockResolvedValue(sarJob);
});
const props = { datasetId: sarDataset.id, jobId: null, onJob: vi.fn(), onRemoved: vi.fn() };
async function enterDraft(saved: boolean) {
  await userEvent.click(await screen.findByRole('button', { name: 'Reference' }));
  const image = await screen.findByRole('img', { name: 'RDKit reference drawing' });
  fireEvent.load(image);
  await userEvent.click(screen.getByRole('button', { name: 'Atom 1 (O)' }));
  if (saved) {
    await userEvent.click(screen.getByRole('button', { name: 'Save region' }));
    await screen.findByText('Region saved · 1 attachment points');
  }
  await userEvent.selectOptions(screen.getByLabelText('Activity metric'), 'metric-control');
  await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
  const grades = screen.getByRole('textbox', { name: /Grade order/ });
  await userEvent.type(grades, 'Strong 原文\nWeak');
  await userEvent.click(screen.getByRole('checkbox', { name: /Known differences still prevent/ }));
  return { image, grades };
}
describe('SAR review: retained drafts do not authorize writes', () => {
  it.each([false, true])(
    'keeps %s-saved selection and analysis drafts while inactive and until both reads revalidate',
    async (saved) => {
      const { rerender } = render(<DatasetWorkbench {...props} active />);
      const draft = await enterDraft(saved);
      const oldSignal = vi.mocked(sarApi.dataset).mock.calls[0]![1];
      rerender(<DatasetWorkbench {...props} active={false} />);
      expect(oldSignal.aborted).toBe(true);
      expect(screen.getByRole('textbox', { name: /Grade order/ })).toBe(draft.grades);
      expect(draft.grades).toHaveValue('Strong 原文\nWeak');
      expect(screen.getByLabelText('Activity direction')).toHaveValue('lower');
      expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
      const metadata = deferred<typeof sarDataset>();
      const drawing = deferred<typeof sarDrawing>();
      vi.mocked(sarApi.dataset).mockReturnValueOnce(metadata.promise);
      vi.mocked(sarApi.drawing).mockReturnValueOnce(drawing.promise);
      rerender(<DatasetWorkbench {...props} active />);
      await waitFor(() => expect(sarApi.dataset).toHaveBeenCalledTimes(2));
      expect(screen.getByLabelText('Activity direction')).toBeDisabled();
      await act(async () => metadata.resolve(sarDataset));
      await waitFor(() => expect(sarApi.drawing).toHaveBeenCalledTimes(2));
      expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
      await act(async () => drawing.resolve(sarDrawing));
      await waitFor(() => expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toBeEnabled());
      expect(screen.getByRole('img', { name: 'RDKit reference drawing' })).toBe(draft.image);
      expect(screen.getByRole('textbox', { name: /Grade order/ })).toBe(draft.grades);
      expect(
        screen.getByRole('checkbox', { name: /Known differences still prevent/ }),
      ).toBeChecked();
      if (saved)
        expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeEnabled();
      else
        expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
      expect(sarApi.saveRegion).toHaveBeenCalledTimes(saved ? 1 : 0);
      expect(sarApi.analyse).not.toHaveBeenCalled();
    },
  );
  it('preserves incomplete selections, text and search through refresh/error, without remounting or treating cached data as current', async () => {
    render(<DatasetWorkbench {...props} active />);
    const draft = await enterDraft(false);
    const search = screen.getByLabelText('Search identifiers or SMILES');
    expect(search).toHaveAttribute('maxlength', '200');
    fireEvent.change(search, { target: { value: '[C@H](O)Cl %_' } });
    await waitFor(() =>
      expect(vi.mocked(sarApi.molecules).mock.calls.at(-1)?.[2]).toBe('[C@H](O)Cl %_'),
    );
    vi.mocked(sarApi.dataset).mockRejectedValueOnce(new Error('read unavailable 原文'));
    const panel = screen.getByRole('heading', { name: sarDataset.title }).closest('section')!;
    await userEvent.click(within(panel).getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('read unavailable 原文');
    expect(screen.getByRole('textbox', { name: /Grade order/ })).toBe(draft.grades);
    expect(draft.grades).toHaveValue('Strong 原文\nWeak');
    expect(search).toHaveValue('[C@H](O)Cl %_');
    expect(screen.getByRole('button', { name: 'Atom 1 (O)' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByRole('button', { name: 'Save region' })).toBeDisabled();
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('textbox', { name: /等级顺序/ })).toBe(draft.grades);
    await userEvent.click(within(panel).getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '保存区域' })).toBeEnabled());
    expect(screen.getByLabelText('搜索编号或 SMILES')).toBe(search);
    expect(sarApi.saveRegion).not.toHaveBeenCalled();
  });
  it('keeps text but invalidates the selected region when revalidation finds a new dataset revision', async () => {
    render(<DatasetWorkbench {...props} active />);
    const draft = await enterDraft(true);
    vi.mocked(sarApi.dataset).mockResolvedValue({ ...sarDataset, revision: 3 });
    const panel = screen.getByRole('heading', { name: sarDataset.title }).closest('section')!;
    await userEvent.click(within(panel).getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(screen.getByText('No atoms selected')).toBeVisible());
    expect(screen.getByRole('textbox', { name: /Grade order/ })).toBe(draft.grades);
    expect(screen.getByLabelText('Activity direction')).toHaveValue('lower');
    expect(screen.getByRole('button', { name: 'Start reference comparison' })).toBeDisabled();
    expect(sarApi.saveRegion).toHaveBeenCalledOnce();
  });
});
describe('SAR review: historical evidence remains inspectable', () => {
  it('gets an ineligible result row source from metadata, not an unavailable drawing', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue(sarJob);
    vi.spyOn(sarApi, 'pairs').mockResolvedValue({
      items: [{ ...sarPair, molecule_id: sarInvalid.id }],
      total: 1,
      page: 1,
      page_size: 50,
      job: sarJob,
    });
    vi.spyOn(sarApi, 'molecule').mockResolvedValue({
      ...sarInvalid,
      source_page: 19,
      observations: [{ ...sarMolecule.observations[0]!, source_page: 20, source_row: 21 }],
    });
    render(<SARResults active dataset={sarDataset} jobId={sarJob.id} onJob={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Source details' }));
    expect(await screen.findByText('missing_smiles')).toBeVisible();
    expect(screen.getByText('graph_conflict')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Original page 20' })).toHaveAttribute(
      'href',
      expect.stringContaining('page=20'),
    );
    expect(screen.getByText('raw target')).toBeVisible();
    expect(screen.getByText('21')).toBeVisible();
    expect(sarApi.molecule).toHaveBeenCalledWith(
      sarDataset.id,
      sarInvalid.id,
      expect.any(AbortSignal),
    );
    expect(sarApi.drawing).not.toHaveBeenCalled();
  });
  it('keeps result filters across inactive/error revalidation but disables resume/export while unverified', async () => {
    vi.spyOn(sarApi, 'job').mockResolvedValue(sarJob);
    vi.spyOn(sarApi, 'pairs').mockResolvedValue({
      items: [sarPair],
      total: 1,
      page: 1,
      page_size: 50,
      job: sarJob,
    });
    const resultProps = { dataset: sarDataset, jobId: sarJob.id, onJob: vi.fn() };
    const { rerender } = render(<SARResults {...resultProps} active />);
    const filter = await screen.findByLabelText('Match filter (current page)');
    await userEvent.selectOptions(filter, 'ambiguous');
    rerender(<SARResults {...resultProps} active={false} />);
    expect(filter).toHaveValue('ambiguous');
    expect(screen.getByRole('button', { name: 'Export all JSON' })).toBeDisabled();
    vi.mocked(sarApi.job).mockRejectedValueOnce(new Error('job read unavailable'));
    rerender(<SARResults {...resultProps} active />);
    expect(await screen.findByRole('alert')).toHaveTextContent('job read unavailable');
    expect(screen.getByLabelText('Match filter (current page)')).toBe(filter);
    expect(filter).toHaveValue('ambiguous');
    expect(screen.getByRole('button', { name: 'Export all CSV' })).toBeDisabled();
  });
});
