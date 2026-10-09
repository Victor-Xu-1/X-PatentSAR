import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { sarApi } from '../src/api/sarApi';
import { ApiError } from '../src/api/errors';
import { UncertainSARWrite } from '../src/api/sarMutation';
import { setLocale } from '../src/i18n';
import { StudySetup } from '../src/features/sar/study/StudySetup';
import { CSVMappingForm } from '../src/features/sar/CSVMappingForm';
import { MoleculeEvidence } from '../src/features/sar/MoleculeEvidence';
import {
  coreRegion,
  csvPreview,
  sarDataset,
  sarDrawing,
  sarMolecule,
  studyContext,
  studyJob,
  studyProfile,
} from './sar-fixtures';
const props = {
  dataset: sarDataset,
  active: true,
  disabled: false,
  scope: 'current',
  onJob: vi.fn(),
};
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  vi.spyOn(sarStudyApi, 'start').mockResolvedValue(studyJob);
  vi.spyOn(sarApi, 'molecules').mockResolvedValue({
    items: [sarMolecule],
    total: 1,
    page: 1,
    page_size: 50,
  });
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
});
async function selectContext(review = true) {
  const check = await screen.findByRole('checkbox', { name: /IC50 原文.*raw assay/ });
  await userEvent.click(check);
  await userEvent.selectOptions(screen.getByLabelText('Activity direction'), 'lower');
  if (review) await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
}
describe('explicit full-study setup', () => {
  it('performs only GET on entry; accepts an overview without regions only after direction selection', async () => {
    render(<StudySetup {...props} />);
    await screen.findByRole('checkbox', { name: /IC50 原文.*raw assay/ });
    expect(sarStudyApi.start).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    await selectContext();
    await userEvent.click(screen.getByRole('button', { name: 'Run full study' }));
    await waitFor(() => expect(props.onJob).toHaveBeenCalledWith(studyJob));
    expect(vi.mocked(sarStudyApi.start).mock.calls[0]?.[1]).toEqual({
      request_id: expect.stringMatching(/^[a-f0-9]{32}$/),
      title: sarDataset.title,
      expected_dataset_revision: 2,
      policies: [
        {
          context_id: studyContext.id,
          direction: 'lower',
          grade_order: [],
          strong_threshold: null,
          threshold_inclusive: false,
          strength_method: 'tenth_decade',
        },
      ],
      region_ids: [],
      core_ids: [],
      candidate_count: 8,
      confirm_context: false,
    });
  });
  it('keeps source-owned condition and language drafts through failed/inactive reads, and disables until revalidated', async () => {
    const { rerender } = render(<StudySetup {...props} />);
    await selectContext(false);
    await userEvent.click(screen.getByText('Source grades (optional)'));
    const grades = screen.getByRole('textbox', { name: /Grade order/ });
    await userEvent.type(grades, 'Strong 原文\nWeak');
    const signal = vi.mocked(sarStudyApi.profile).mock.calls[0]![2];
    rerender(<StudySetup {...props} active={false} />);
    expect(signal.aborted).toBe(true);
    expect(grades).toHaveValue('Strong 原文\nWeak');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    vi.mocked(sarStudyApi.profile).mockRejectedValueOnce(new Error('profile 原文 unavailable'));
    rerender(<StudySetup {...props} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('profile 原文 unavailable');
    await act(() => setLocale('zh-CN'));
    expect(screen.getByRole('textbox', { name: /等级顺序/ })).toBe(grades);
    expect(screen.getByRole('button', { name: '下一步' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '下一步' })).toBeEnabled());
    expect(sarStudyApi.start).not.toHaveBeenCalled();
  });
  it('requires unique source grades without numeric overrides and keeps saved core and variable IDs distinct', async () => {
    render(<StudySetup {...props} />);
    await selectContext(false);
    await userEvent.click(screen.getByText('Source grades (optional)'));
    const grade = screen.getByRole('textbox', { name: /Grade order/ });
    await userEvent.type(grade, 'Strong\nStrong');
    expect(
      screen.queryByLabelText('Strong-activity threshold (optional, raw value)'),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
    await userEvent.clear(grade);
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await userEvent.click(screen.getByText(/Confirmed cores \(optional\)/));
    await userEvent.click(screen.getByRole('checkbox', { name: /Core 原文/ }));
    await userEvent.click(screen.getByText(/Variable regions \(optional\)/));
    await userEvent.click(screen.getByRole('checkbox', { name: /R1 用户原文/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Run full study' }));
    expect(vi.mocked(sarStudyApi.start).mock.calls[0]?.[1]).toMatchObject({
      core_ids: [coreRegion.id],
      region_ids: [studyProfile.regions[0]!.id],
    });
  });
  it('preserves uncertain payload/nonce and requires a deliberate retry', async () => {
    const start = vi.mocked(sarStudyApi.start).mockImplementationOnce(async (_id, body) => {
      throw new UncertainSARWrite(
        new ApiError(503, 'sar_unknown', 'Unknown outcome'),
        body.request_id,
      );
    });
    render(<StudySetup {...props} />);
    await selectContext();
    await userEvent.click(screen.getByRole('button', { name: 'Run full study' }));
    const retry = await screen.findByRole('button', {
      name: /retry with the same request identity/,
    });
    expect(start).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Study title')).toBeDisabled();
    await userEvent.click(retry);
    await waitFor(() => expect(start).toHaveBeenCalledTimes(2));
    expect(start.mock.calls[1]?.[1]).toEqual(start.mock.calls[0]?.[1]);
  });
  it('ignores a late successful study after a newer owner context is selected', async () => {
    let resolve!: (value: typeof studyJob) => void;
    vi.mocked(sarStudyApi.start).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const onJob = vi.fn(),
      { rerender } = render(<StudySetup {...props} onJob={onJob} />);
    await selectContext();
    await userEvent.click(screen.getByRole('button', { name: 'Run full study' }));
    rerender(<StudySetup {...props} scope="new-owner" onJob={onJob} />);
    await act(async () => resolve(studyJob));
    expect(onJob).not.toHaveBeenCalled();
  });
  it('saves a named confirmed core using exact backend atom identity, never an editor renumbering', async () => {
    const save = vi
      .spyOn(sarApi, 'saveRegion')
      .mockResolvedValue({ ...coreRegion, atom_indices: [1], name: 'Core 用户' });
    render(<StudySetup {...props} />);
    await selectContext();
    await userEvent.click(screen.getByText('Add a named selection'));
    await userEvent.click(await screen.findByRole('button', { name: 'Reference' }));
    fireEvent.load(await screen.findByRole('img', { name: 'RDKit reference drawing' }));
    await userEvent.selectOptions(screen.getByLabelText('Selection purpose'), 'core');
    const name = screen.getByLabelText('Selection name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Core 用户');
    await userEvent.click(screen.getByRole('button', { name: 'Atom 1 (O)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save region' }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0]?.[1]).toEqual({
      molecule_id: sarMolecule.id,
      expected_dataset_revision: 2,
      expected_graph_sha256: sarMolecule.graph_sha256,
      atom_indices: [1],
      name: 'Core 用户',
      kind: 'core',
    });
    await waitFor(() => expect(sarStudyApi.profile).toHaveBeenCalledTimes(2));
  });
});
describe('captured CSV and page evidence', () => {
  it('offers collapsed research mappings and an explicit PDF page column, without assigning unknown headers', async () => {
    const onSubmit = vi.fn();
    render(
      <CSVMappingForm
        preview={{ ...csvPreview, headers: [...csvPreview.headers, 'mw', 'risk', 'pdfpage'] }}
        disabled={false}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByLabelText('PDF source-page column (optional)')).toHaveValue('');
    await userEvent.selectOptions(
      screen.getByLabelText('PDF source-page column (optional)'),
      'pdfpage',
    );
    await userEvent.click(screen.getByText('Captured properties and predictions (optional)'));
    expect(screen.getByLabelText('molecular_weight')).toHaveValue('');
    await userEvent.selectOptions(screen.getByLabelText('molecular_weight'), 'mw');
    await userEvent.selectOptions(screen.getByLabelText('hERG'), 'risk');
    await userEvent.click(screen.getByRole('button', { name: 'Create CSV dataset' }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        source_page_column: 'pdfpage',
        property_columns: { molecular_weight: 'mw' },
        prediction_columns: { hERG: 'risk' },
      }),
    );
  });
  it('renders PDF page 79 and CSV record row 1 as different evidence, with no fabricated PDF link', () => {
    render(
      <MoleculeEvidence
        dataset={{ ...sarDataset, source_kind: 'csv', source_project_id: null }}
        molecule={{
          ...sarMolecule,
          source_page: 79,
          observations: [
            {
              ...sarMolecule.observations[0]!,
              source_kind: 'imported',
              source_page: 79,
              source_row: 1,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText('PDF source page 79 (PDF not attached)')).toBeVisible();
    expect(screen.getByText('source_page')).toBeVisible();
    expect(screen.getByText('source_row')).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
