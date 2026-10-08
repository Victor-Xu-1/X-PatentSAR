import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { setLocale } from '../src/i18n';
import { StudyResults } from '../src/features/sar/study/StudyResults';
import { StudyReportView } from '../src/features/sar/study/StudyReportView';
import { StudyImage } from '../src/features/sar/study/StudyImage';
import {
  propertyText,
  selectedContexts,
  sortStudyPage,
} from '../src/features/sar/study/tablePresentation';
import {
  sarDataset,
  sarDrawing,
  sarMolecule,
  studyContext,
  studyJob,
  studyProfile,
  studyReport,
  studyRow,
} from './sar-fixtures';
beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'job').mockResolvedValue(studyJob);
  vi.spyOn(sarStudyApi, 'profile').mockResolvedValue(studyProfile);
  vi.spyOn(sarStudyApi, 'overview').mockResolvedValue({ job: studyJob, report: studyReport });
  vi.spyOn(sarStudyApi, 'drawing').mockImplementation(async (_id, _kind, identifier) => ({
    id: identifier,
    svg: sarDrawing.svg,
  }));
  vi.spyOn(sarStudyApi, 'rows').mockImplementation(async (_id, _dataset, page) => ({
    job: studyJob,
    items: [studyRow],
    total: 70,
    page,
    page_size: 50,
  }));
  vi.spyOn(sarApi, 'molecule').mockResolvedValue(sarMolecule);
});
const props = {
  dataset: sarDataset,
  jobId: studyJob.id,
  active: true,
  disabled: false,
  scope: 'current',
  onJob: vi.fn(),
};
describe('complete study report and lifecycle', () => {
  it('distinguishes all checked attempts, actual matches, comparable evidence and observed compounds vs observations', async () => {
    render(<StudyResults {...props} />);
    await screen.findByText(studyReport.title);
    const checked = screen.getByText('Comparisons checked').closest('div')!;
    expect(within(checked).getByText('2')).toBeVisible();
    expect(
      within(screen.getByText('Matched comparisons').closest('div')!).getByText('1'),
    ).toBeVisible();
    expect(
      within(screen.getByText('Comparable comparisons').closest('div')!).getByText('1'),
    ).toBeVisible();
    const meter = screen.getByRole('meter', { name: '<10 · Molecules' });
    expect(meter).toHaveAttribute('value', '1');
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Counting unit' }),
      'observations',
    );
    expect(screen.getByRole('meter', { name: '<10 · Observations' })).toHaveAttribute('value', '2');
    expect(sarStudyApi.rows).not.toHaveBeenCalled();
    expect(sarStudyApi.drawing).not.toHaveBeenCalled();
  });
  it('uses human core/fragment labels and exact immutable drawing/filter IDs, keeping no-variation and counterexamples visible', async () => {
    render(<StudyResults {...props} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Scaffolds' }));
    expect(await screen.findByText('Core 原文')).toBeVisible();
    expect(screen.queryByText('core/control')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Variable regions' }));
    const regionView = within(screen.getByRole('region', { name: 'Variable regions' }));
    expect(
      regionView.getByText('No structural variation was observed in this region.'),
    ).toBeVisible();
    expect(regionView.getByRole('heading', { name: /Fragment 1/ })).toBeVisible();
    expect(regionView.getByText('Better 0 · Worse 1 · Indeterminate 1 · Missing 0')).toBeVisible();
    expect(screen.queryByText('fragment/control')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'View support and counterexamples' }));
    await waitFor(() => expect(sarStudyApi.rows).toHaveBeenCalled());
    expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3]).toMatchObject({
      region_id: studyReport.regions[0]!.region.id,
      fragment_id: 'fragment/control',
    });
  });
  it('shows candidates with captured facts and ties policy, not a local drug score or rewritten raw activity', async () => {
    render(<StudyResults {...props} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Leads' }));
    expect(screen.getByRole('heading', { name: sarMolecule.label })).toBeVisible();
    expect(within(screen.getByRole('region', { name: 'Leads' })).getAllByText('<10')).toHaveLength(
      2,
    );
    await userEvent.click(screen.getByText('Candidate policy and ties'));
    expect(screen.getByText('strict-context-pareto-v1')).toBeVisible();
    await userEvent.click(screen.getByText('Properties and captured predictions'));
    expect(screen.getByText(/120.00/)).toBeVisible();
    expect(screen.getByText('0.24')).toBeVisible();
    expect(screen.getByText(/manual_null/)).toBeVisible();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });
  it.each(['queued', 'running', 'cancelled', 'interrupted', 'failed'] as const)(
    'does not publish or export a %s partial job as success',
    async (status) => {
      vi.mocked(sarApi.job).mockResolvedValue({
        ...studyJob,
        status,
        error_code: status === 'failed' ? 'sar_attempt_budget' : null,
      });
      render(<StudyResults {...props} />);
      await screen.findByText(
        'The full report is published only after completion. Partial progress is not a scientific conclusion.',
      );
      expect(sarStudyApi.overview).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: 'Export report JSON' })).toBeDisabled();
      if (status === 'failed')
        expect(await screen.findByRole('alert')).toHaveTextContent('sar_attempt_budget');
    },
  );
  it('cancels/resumes only explicit current jobs, blocks stale resume, and aborts reads when inactive', async () => {
    vi.mocked(sarApi.job).mockResolvedValue({ ...studyJob, status: 'running' });
    const cancel = vi
      .spyOn(sarApi, 'cancel')
      .mockResolvedValue({ ...studyJob, status: 'cancelled' });
    const { rerender } = render(<StudyResults {...props} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel SAR job' }));
    expect(cancel).toHaveBeenCalledExactlyOnceWith(studyJob.id, sarDataset.id);
    vi.mocked(sarApi.job).mockResolvedValue({ ...studyJob, status: 'interrupted', stale: true });
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByRole('button', { name: 'Resume SAR job' })).toBeDisabled();
    const signal = vi.mocked(sarApi.job).mock.calls.at(-1)![2];
    rerender(<StudyResults {...props} active={false} />);
    expect(signal.aborted).toBe(true);
  });
  it('downloads complete authenticated bytes for all four formats without executing HTML', async () => {
    const exportApi = vi
      .spyOn(sarStudyApi, 'export')
      .mockResolvedValue(new Blob(['original raw bytes']));
    const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.stubGlobal(
      'URL',
      Object.assign(URL, {
        createObjectURL: vi.fn(() => 'blob:controlled'),
        revokeObjectURL: vi.fn(),
      }),
    );
    render(<StudyResults {...props} />);
    for (const format of ['CSV', 'JSON', 'SDF', 'HTML']) {
      const button = await screen.findByRole('button', { name: 'Export report ' + format });
      await waitFor(() => expect(button).toBeEnabled());
      await userEvent.click(button);
      await waitFor(() => expect(download).toHaveBeenCalledTimes(exportApi.mock.calls.length));
    }
    expect(exportApi.mock.calls.map((call) => call[1])).toEqual(['csv', 'json', 'sdf', 'html']);
    expect(document.querySelector('iframe')).toBeNull();
  });
  it('rejects active SVG contents and unsafe URLs before any image DOM is inserted', async () => {
    vi.mocked(sarStudyApi.drawing).mockResolvedValue({
      id: sarMolecule.id,
      svg: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><foreignObject/></svg>',
    });
    render(
      <StudyImage
        jobId={studyJob.id}
        kind="molecule"
        identifier={sarMolecule.id}
        label={sarMolecule.label}
        active
      />,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Unsafe or invalid SVG');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});
describe('compact activity-table presentation', () => {
  it('uses only selected contexts, short property headings/2dp, server filtering/paging and shared column chooser', async () => {
    const report = {
      ...studyReport,
      contexts: [
        studyContext,
        { ...studyContext, id: '6'.repeat(64), name: 'Unselected context 原文' },
      ],
    };
    render(<StudyReportView report={report} dataset={sarDataset} jobId={studyJob.id} active />);
    await userEvent.click(screen.getByRole('button', { name: 'Activity table' }));
    let table = await screen.findByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'MW' })).toBeVisible();
    expect(
      within(table).queryByRole('columnheader', { name: 'Unselected context 原文' }),
    ).not.toBeInTheDocument();
    expect(within(table).getByText('120.00')).toBeVisible();
    expect(within(table).queryByText('raw_reason 原文')).not.toBeInTheDocument();
    expect(within(table).queryByText('rdkit_computed')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[2]).toBe(2));
    table = await screen.findByRole('table');
    const calls = vi.mocked(sarStudyApi.rows).mock.calls.length;
    await userEvent.click(within(table).getByRole('button', { name: 'Source details' }));
    await screen.findByRole('complementary', { name: 'Source details' });
    expect(vi.mocked(sarStudyApi.rows).mock.calls.length).toBe(calls);
    await userEvent.click(screen.getByRole('button', { name: 'Column settings' }));
    const dialog = within(screen.getByRole('dialog'));
    await userEvent.click(dialog.getByRole('checkbox', { name: /Show column MW/ }));
    await userEvent.click(dialog.getAllByRole('button', { name: 'Close dialog' })[0]!);
    expect(within(table).queryByRole('columnheader', { name: 'MW' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search identifiers or SMILES'), {
      target: { value: '[C@H](O)Cl %_' },
    });
    await waitFor(() =>
      expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3].query).toBe('[C@H](O)Cl %_'),
    );
    await act(() => setLocale('zh-CN'));
    expect(screen.getByLabelText('搜索编号或 SMILES')).toHaveValue('[C@H](O)Cl %_');
  });
  it('formats only finite supplied numbers and sorts only a copy of the current page with nulls last', () => {
    expect(propertyText(null)).toBe('—');
    expect(propertyText(NaN)).toBe('—');
    expect(propertyText(1.234)).toBe('1.23');
    expect(
      selectedContexts({
        ...studyReport,
        contexts: [studyContext, { ...studyContext, id: 'unused' }],
      }),
    ).toEqual([studyContext]);
    const rows = [
      studyRow,
      { ...studyRow, label: 'ID 2', properties: { molecular_weight: 10 } },
      { ...studyRow, label: 'missing', properties: {} },
    ];
    expect(
      sortStudyPage(rows, { column: 'property:molecular_weight', direction: 'asc' }).map(
        (r) => r.label,
      ),
    ).toEqual(['ID 2', studyRow.label, 'missing']);
    expect(rows[0]).toBe(studyRow);
  });
});
