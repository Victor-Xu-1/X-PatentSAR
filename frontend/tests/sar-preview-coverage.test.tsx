import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { decodeStudyPreview } from '../src/api/sarPreviewDecoder';
import { TransformationPreview } from '../src/features/sar/study/TransformationPreview';
import { PreviewMeasurements } from '../src/features/sar/study/PreviewMeasurements';
import { setLocale } from '../src/i18n';
import { sarDrawing, sarPair, studyContext, studyJob, studyReport, studyRow } from './sar-fixtures';

const summary = studyReport.regions[0]!;
const candidates = [
  { ...studyRow, molecule_id: 'candidate-2', label: 'P2' },
  { ...studyRow, molecule_id: 'candidate-3', label: 'P3' },
];
const supportingContext = {
  ...studyContext,
  id: 'a'.repeat(64),
  metric_id: 'pk-clearance-control',
  name: 'CL 原文 (mL/min/kg)',
  unit: 'mL/min/kg',
};
const packet = {
  job: studyJob,
  region: summary.region,
  reference: studyRow,
  candidate: candidates[0]!,
  pair: {
    ...sarPair,
    reference_id: studyRow.molecule_id,
    molecule_id: candidates[0]!.molecule_id,
    region_id: summary.region.id,
    match_status: 'matched' as const,
  },
  measurements: [
    {
      context_id: studyContext.id,
      reference_values: ['10'],
      candidate_values: ['1'],
      comparison: 'better',
      evidence_basis: 'recorded_context',
      raw_difference: -9,
    },
  ],
  property_differences: {},
  recorded_measurements: [
    { context_id: supportingContext.id, reference_values: ['<6', ''], candidate_values: ['2'] },
  ],
};

beforeEach(() => {
  setLocale('en');
  vi.spyOn(sarStudyApi, 'drawing').mockResolvedValue({
    id: studyRow.molecule_id,
    svg: sarDrawing.svg,
  });
  vi.spyOn(sarStudyApi, 'preview').mockImplementation(async (_job, _dataset, _region, molecule) => {
    const candidate = candidates.find((row) => row.molecule_id === molecule)!;
    return { ...packet, candidate, pair: { ...packet.pair, molecule_id: molecule } };
  });
  vi.spyOn(sarStudyApi, 'rows').mockImplementation(async (_job, _dataset, _page, filters) => ({
    job: studyJob,
    items:
      filters.scope === 'changes' && !filters.fragment_id ? candidates : candidates.slice(0, 1),
    total: filters.scope === 'changes' && !filters.fragment_id ? 2 : 1,
    page: 1,
    page_size: 50,
  }));
});

it('offers all recorded changed fragments for the same region and switches exact candidate without a write', async () => {
  const report = { ...studyReport, contexts: [studyContext, supportingContext] };
  render(
    <TransformationPreview
      report={report}
      summary={{
        ...summary,
        fragments: candidates.map((row, index) => ({
          ...summary.fragments[0]!,
          id: String(index + 1).repeat(64),
          is_reference: false,
          molecule_ids: [row.molecule_id],
        })),
      }}
      moleculeId={candidates[0]!.molecule_id}
      jobId={studyJob.id}
      active
      onSource={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const select = await screen.findByRole('combobox', { name: 'Modified compound' });
  await within(select).findByRole('option', { name: 'P3' });
  expect(sarStudyApi.rows).toHaveBeenCalledWith(
    studyJob.id,
    studyReport.dataset_id,
    1,
    expect.objectContaining({ scope: 'changes', region_id: summary.region.id, fragment_id: '' }),
    expect.any(AbortSignal),
  );
  await userEvent.selectOptions(select, candidates[1]!.molecule_id);
  expect(sarStudyApi.preview).toHaveBeenLastCalledWith(
    studyJob.id,
    studyReport.dataset_id,
    summary.region.id,
    candidates[1]!.molecule_id,
    expect.any(AbortSignal),
  );
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('combobox', { name: '改造化合物' })).toHaveValue(
    candidates[1]!.molecule_id,
  );
});

it('shows unselected raw PK/censored/missing readings separately from statistical conclusions and preserves locale identity', async () => {
  const data = decodeStudyPreview(packet);
  const original = JSON.stringify(data);
  const report = { ...studyReport, contexts: [studyContext, supportingContext] };
  render(<PreviewMeasurements data={data} report={report} />);
  const table = screen.getByRole('table', { name: 'Recorded values' });
  const raw = within(table).getByRole('rowheader', { name: supportingContext.name }).closest('tr')!;
  expect(within(raw).getByText('<6 · —')).toBeVisible();
  expect(within(raw).getByText('2')).toBeVisible();
  expect(within(raw).queryByText(/Δ|Lower|Stronger|Indeterminate/)).not.toBeInTheDocument();
  expect(within(raw).getByLabelText('Not assessed in this study')).toHaveTextContent('—');
  await act(() => setLocale('zh-CN'));
  expect(within(raw).getByRole('rowheader')).toHaveTextContent(supportingContext.name);
  expect(within(raw).getByLabelText('未纳入本次统计')).toHaveTextContent('—');
  expect(JSON.stringify(data)).toBe(original);
});

it('accepts an old preview without additive records but rejects malformed, duplicate and overlapping raw context records', () => {
  const { recorded_measurements, ...legacy } = packet;
  expect(decodeStudyPreview(legacy).candidate.label).toBe('P2');
  for (const extra of [
    null,
    [...recorded_measurements, ...recorded_measurements],
    [{ ...recorded_measurements[0]!, context_id: studyContext.id }],
    [{ ...recorded_measurements[0]!, candidate_values: [123] }],
    Array.from({ length: 1001 }, (_, index) => ({
      ...recorded_measurements[0]!,
      context_id: index.toString(16).padStart(64, '0'),
    })),
  ])
    expect(() => decodeStudyPreview({ ...packet, recorded_measurements: extra })).toThrow();
});

it('refuses a supporting context absent from the captured report instead of showing unlabelled or misassigned values', () => {
  render(<PreviewMeasurements data={decodeStudyPreview(packet)} report={studyReport} />);
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.queryByRole('table', { name: 'Recorded values' })).not.toBeInTheDocument();
});
