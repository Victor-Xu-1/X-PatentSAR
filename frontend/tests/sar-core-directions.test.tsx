import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarApi } from '../src/api/sarApi';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { StudyNetwork } from '../src/features/sar/study/StudyNetwork';
import { NetworkBranchCard } from '../src/features/sar/study/NetworkBranchCard';
import { StudyReportView } from '../src/features/sar/study/StudyReportView';
import { setLocale } from '../src/i18n';
import {
  sarDataset,
  sarDrawing,
  studyFragment,
  studyJob,
  studyReport,
  studyRow,
} from './sar-fixtures';

const base = studyReport.regions[0]!;
const sites = [
  {
    ...base,
    no_variation: false,
    matched: 2,
    origin: 'single_site' as const,
    region: { ...base.region, id: 'direction-a', atom_indices: [0] },
    fragments: [{ ...studyFragment, is_reference: false, molecule_ids: ['a', 'shared'] }],
  },
  {
    ...base,
    no_variation: false,
    matched: 2,
    origin: 'single_site' as const,
    region: { ...base.region, id: 'direction-b', atom_indices: [1] },
    fragments: [{ ...studyFragment, is_reference: false, molecule_ids: ['b', 'shared'] }],
  },
];
const report = { ...studyReport, regions: sites };
const rows = ['a', 'b', 'shared'].map((id) => ({
  ...studyRow,
  molecule_id: id,
  label: '原文 ' + id,
}));

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarApi, 'drawing').mockResolvedValue(sarDrawing);
  vi.spyOn(sarStudyApi, 'drawing').mockImplementation(async (_job, _kind, id) => ({
    id,
    svg: sarDrawing.svg,
  }));
  vi.spyOn(sarStudyApi, 'rows').mockResolvedValue({
    job: studyJob,
    items: rows,
    total: 3,
    page: 1,
    page_size: 6,
  });
});

it('starts with all proved directions through one paged read and one card per original candidate', async () => {
  const original = JSON.stringify(report);
  render(<StudyNetwork report={report} jobId={studyJob.id} active onSource={vi.fn()} />);
  await screen.findByRole('button', { name: 'Compare 原文 shared' });
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(1);
  expect(vi.mocked(sarStudyApi.rows).mock.calls[0]![3]).toMatchObject({
    scope: 'changes',
    reference_id: base.region.molecule_id,
    region_id: '',
  });
  expect(screen.getByRole('button', { name: 'All directions' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  const cards = document.querySelectorAll('.sar-network-branch');
  expect(cards).toHaveLength(3);
  const shared = [...cards].find((card) =>
    within(card as HTMLElement).queryByRole('button', { name: 'Compare 原文 shared' }),
  )!;
  expect(
    within(shared as HTMLElement).getByRole('button', { name: 'View region R1' }),
  ).toBeVisible();
  expect(
    within(shared as HTMLElement).getByRole('button', { name: 'View region R2' }),
  ).toBeVisible();
  expect(JSON.stringify(report)).toBe(original);
});

it('site selection narrows the same source path and all-directions restores it without language/data rewriting', async () => {
  render(<StudyNetwork report={report} jobId={studyJob.id} active onSource={vi.fn()} />);
  await screen.findByRole('button', { name: 'Compare 原文 shared' });
  await userEvent.click(
    within(document.querySelector('.sar-region-legend') as HTMLElement).getByRole('button', {
      name: 'R2',
    }),
  );
  await waitFor(() =>
    expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3]).toMatchObject({
      reference_id: base.region.molecule_id,
      region_id: 'direction-b',
    }),
  );
  await userEvent.click(screen.getByRole('button', { name: 'All directions' }));
  await waitFor(() =>
    expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3].region_id).toBe(''),
  );
  const control = screen.getByRole('button', { name: 'All directions' });
  control.focus();
  const calls = vi.mocked(sarStudyApi.rows).mock.calls.length;
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('button', { name: '全部改造方向' })).toBe(control);
  expect(control).toHaveFocus();
  expect(screen.getByRole('button', { name: '比较 原文 shared' })).toBeVisible();
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(calls);
});

it('keeps many valid explanations in one bounded native selector rather than a wall of controls', async () => {
  const many = Array.from({ length: 9 }, (_, index) => ({
    ...sites[0]!,
    region: {
      ...sites[0]!.region,
      id: 'explanation-' + index,
      name: 'R' + (index + 90) + ' original',
    },
  }));
  const original = JSON.stringify(many),
    compare = vi.fn();
  render(
    <NetworkBranchCard
      row={rows[0]!}
      report={report}
      sites={many}
      jobId={studyJob.id}
      active
      fragments={false}
      onCompare={compare}
    />,
  );
  const choice = screen.getByRole('combobox', { name: 'Variable regions · 原文 a' });
  expect(within(choice).getAllByRole('option')).toHaveLength(9);
  await userEvent.selectOptions(choice, 'explanation-8');
  await userEvent.click(screen.getByRole('button', { name: 'Compare 原文 a' }));
  expect(compare).toHaveBeenCalledWith(many[8], 'a', expect.any(HTMLButtonElement));
  expect(JSON.stringify(many)).toBe(original);
});

it('does not make branch or drawing requests for an inactive core workbench', () => {
  render(<StudyNetwork report={report} jobId={studyJob.id} active={false} onSource={vi.fn()} />);
  expect(sarStudyApi.rows).not.toHaveBeenCalled();
  expect(sarStudyApi.drawing).not.toHaveBeenCalled();
  expect(sarApi.drawing).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: /^Compare / })).not.toBeInTheDocument();
});

it('shows a verified empty union without inventing a modification', async () => {
  vi.mocked(sarStudyApi.rows).mockResolvedValue({
    job: studyJob,
    items: [],
    total: 0,
    page: 1,
    page_size: 6,
  });
  render(<StudyNetwork report={report} jobId={studyJob.id} active onSource={vi.fn()} />);
  expect(await screen.findByText('No matching structure branches')).toBeVisible();
  expect(screen.queryByRole('button', { name: /^Compare / })).not.toBeInTheDocument();
});

it('keeps a failed core read distinct from a verified empty union', async () => {
  vi.mocked(sarStudyApi.rows).mockRejectedValue(new Error('controlled current read failure'));
  render(<StudyNetwork report={report} jobId={studyJob.id} active onSource={vi.fn()} />);
  expect(await screen.findByRole('alert')).toBeVisible();
  expect(screen.queryByText('No matching structure branches')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Compare / })).not.toBeInTheDocument();
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(1);
});

it('uses the same all-direction workbench for manual reports without reclassifying their regions', async () => {
  const manual = {
    ...report,
    discovery: null,
    regions: sites.map((item, index) => ({
      ...item,
      origin: 'manual' as const,
      region: { ...item.region, name: ['Linker 原文', 'Ring 原文'][index]! },
    })),
  };
  const original = JSON.stringify(manual);
  render(<StudyReportView report={manual} dataset={sarDataset} jobId={studyJob.id} active />);
  await userEvent.click(screen.getByRole('button', { name: 'Variable regions' }));
  const panel = within(screen.getByRole('region', { name: 'Variable regions' }));
  expect(await panel.findByRole('button', { name: 'Compare 原文 shared' })).toBeVisible();
  expect(panel.getByRole('button', { name: 'All directions' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(sarStudyApi.rows).toHaveBeenCalledTimes(1);
  expect(vi.mocked(sarStudyApi.rows).mock.calls[0]![3]).toMatchObject({
    scope: 'changes',
    reference_id: base.region.molecule_id,
    region_id: '',
  });
  expect(panel.queryByText('Search coverage')).not.toBeInTheDocument();
  const legend = panel.getByRole('button', { name: 'Ring 原文' });
  await userEvent.click(legend);
  await waitFor(() =>
    expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3].region_id).toBe('direction-b'),
  );
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('button', { name: 'Ring 原文' })).toBe(legend);
  expect(legend).toHaveAttribute('aria-pressed', 'true');
  expect(JSON.stringify(manual)).toBe(original);
});

it('retains manual no-variation and unproved regions without admitting a changed candidate', async () => {
  const manual = {
    ...studyReport,
    discovery: null,
    regions: [{ ...base, origin: 'manual' as const, matched: 0, ineligible: 3 }],
  };
  vi.mocked(sarStudyApi.rows).mockResolvedValue({
    job: studyJob,
    items: [],
    total: 0,
    page: 1,
    page_size: 6,
  });
  const original = JSON.stringify(manual);
  render(<StudyNetwork report={manual} jobId={studyJob.id} active onSource={vi.fn()} />);
  expect(screen.getByRole('button', { name: 'Select core ' + base.reference_label })).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: base.region.name! }));
  expect(
    await screen.findByText('No structural variation was observed in this region.'),
  ).toBeVisible();
  expect(await screen.findByText('No matching structure branches')).toBeVisible();
  expect(screen.queryByRole('button', { name: /^Compare / })).not.toBeInTheDocument();
  expect(JSON.stringify(manual)).toBe(original);
});

it('keeps a manual study without selected regions explicitly empty and makes no candidate request', () => {
  render(
    <StudyNetwork
      report={{ ...studyReport, discovery: null, regions: [] }}
      jobId={studyJob.id}
      active
      onSource={vi.fn()}
    />,
  );
  expect(
    screen.getByText(
      'No regions were selected for this study. Save regions, then explicitly run a new study.',
    ),
  ).toBeVisible();
  expect(sarStudyApi.rows).not.toHaveBeenCalled();
  expect(sarApi.drawing).not.toHaveBeenCalled();
});

it('switches original manual cores without merging region identities or candidate pools', async () => {
  const first = { ...sites[0]!, origin: 'manual' as const };
  const second = {
    ...sites[1]!,
    origin: 'manual' as const,
    reference_label: 'Example I-255',
    region: { ...sites[1]!.region, molecule_id: 'other-reference', name: 'R9 source' },
  };
  vi.mocked(sarStudyApi.rows).mockImplementation(async (_job, _dataset, page, filter) => ({
    job: studyJob,
    total: 1,
    page,
    page_size: 6,
    items: [filter.reference_id === second.region.molecule_id ? rows[1]! : rows[0]!],
  }));
  const manual = { ...report, discovery: null, regions: [first, second] };
  const original = JSON.stringify(manual);
  render(<StudyNetwork report={manual} jobId={studyJob.id} active onSource={vi.fn()} />);
  await userEvent.click(
    screen.getByRole('button', { name: 'Select core ' + first.reference_label }),
  );
  await screen.findByRole('button', { name: 'Compare 原文 a' });
  await userEvent.click(screen.getByRole('button', { name: 'Select core Example I-255' }));
  expect(await screen.findByRole('button', { name: 'Compare 原文 b' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Compare 原文 a' })).not.toBeInTheDocument();
  expect(vi.mocked(sarStudyApi.rows).mock.calls.at(-1)?.[3]).toMatchObject({
    reference_id: second.region.molecule_id,
    region_id: '',
    scope: 'changes',
  });
  expect(
    within(document.querySelector('.sar-region-legend') as HTMLElement).getAllByRole('button'),
  ).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'R9 source' })).toBeVisible();
  expect(JSON.stringify(manual)).toBe(original);
});
