import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { sarStudyApi } from '../src/api/sarStudyApi';
import { createSARStudyApi } from '../src/api/sarStudyApi';
import { ApiClient } from '../src/api/client';
import { json, session } from './fixtures';
import { decodeStudyMatrix } from '../src/api/sarMatrixDecoder';
import { NetworkMatrix } from '../src/features/sar/study/NetworkMatrix';
import { useMediaQuery } from '../src/hooks/useMediaQuery';
import { setLocale } from '../src/i18n';
import { sarDrawing, sarPair, studyContext, studyJob, studyReport, studyRow } from './sar-fixtures';

const rawContext = {
  ...studyContext,
  id: 'f'.repeat(64),
  name: 'CL 原文 (mL/min/kg)',
  unit: 'mL/min/kg',
};
vi.mock('../src/hooks/useMediaQuery', () => ({ useMediaQuery: vi.fn(() => false) }));
const report = { ...studyReport, contexts: [studyContext, rawContext] };
const rows = [2, 3].map((number) => ({
  ...studyRow,
  molecule_id: 'P' + number,
  label: 'I-' + number,
}));
const site = {
  ...report.regions[0]!,
  fragments: rows.map((row, index) => ({
    ...report.regions[0]!.fragments[0]!,
    id: String(index).repeat(64),
    is_reference: false,
    molecule_ids: [row.molecule_id],
  })),
};
const packet = {
  reference_drawing: { id: studyRow.molecule_id, svg: sarDrawing.svg },
  previews: rows.map((row, index) => ({
    job: studyJob,
    region: site.region,
    reference: studyRow,
    candidate: row,
    pair: {
      ...sarPair,
      reference_id: studyRow.molecule_id,
      molecule_id: row.molecule_id,
      region_id: site.region.id,
      match_status: 'matched',
    },
    measurements: [
      {
        context_id: studyContext.id,
        reference_values: ['10'],
        candidate_values: index === 0 ? ['1'] : ['<0.5', '>9'],
        comparison: index === 0 ? 'better' : 'indeterminate',
        evidence_basis: 'recorded_context',
        raw_difference: index === 0 ? -9 : null,
      },
    ],
    recorded_measurements: [
      {
        context_id: rawContext.id,
        reference_values: ['2'],
        candidate_values: index === 0 ? ['<6', ''] : [],
      },
    ],
    property_differences: { molecular_weight: 0, Solubility_AqSolDB: null },
    drawings: {
      reference: { id: studyRow.molecule_id, svg: sarDrawing.svg },
      candidate: { id: row.molecule_id, svg: sarDrawing.svg },
      layout: 'fixed_background',
      equivalent_mappings: 1,
      reason: null,
    },
  })),
};
const props = {
  rows,
  report,
  sites: [site],
  siteOrder: new Map([[site.region.id, 0]]),
  referenceId: studyRow.molecule_id,
  jobId: studyJob.id,
  active: true,
  onCompare: vi.fn(),
  onSource: vi.fn(),
};

beforeEach(() => {
  vi.mocked(useMediaQuery).mockReturnValue(false);
  setLocale('en');
  vi.spyOn(sarStudyApi, 'matrix').mockResolvedValue(decodeStudyMatrix(packet));
  vi.spyOn(sarStudyApi, 'drawing');
  props.onCompare.mockClear();
  props.onSource.mockClear();
});

it('keeps a reference/candidate pair on narrow screens and preserves selection across resize and locale without new reads', async () => {
  vi.mocked(useMediaQuery).mockReturnValue(true);
  const before = JSON.stringify(packet);
  const { rerender } = render(<NetworkMatrix {...props} />);
  const table = await screen.findByRole('table', { name: 'Structure comparison' });
  expect(within(table).getAllByRole('columnheader')).toHaveLength(3);
  expect(screen.getByRole('button', { name: 'Previous structures' })).toBeDisabled();
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: 'Comparison molecule' }),
    'P3',
  );
  expect(within(table).getByRole('button', { name: 'Compare I-3' })).toBeVisible();
  expect(within(table).queryByRole('button', { name: 'Compare I-2' })).not.toBeInTheDocument();
  expect(table).toHaveTextContent('<0.5 · >9');
  expect(screen.getByRole('button', { name: 'Next structures' })).toBeDisabled();
  vi.mocked(useMediaQuery).mockReturnValue(false);
  rerender(<NetworkMatrix {...props} />);
  expect(within(table).getAllByRole('columnheader')).toHaveLength(4);
  vi.mocked(useMediaQuery).mockReturnValue(true);
  rerender(<NetworkMatrix {...props} />);
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('combobox', { name: '对比分子' })).toHaveValue('P3');
  expect(within(table).getByRole('button', { name: '比较 I-3' })).toBeVisible();
  expect(sarStudyApi.matrix).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(packet)).toBe(before);
});

it('shows reference and multiple candidates with one metric label and all six property rows', async () => {
  render(<NetworkMatrix {...props} />);
  const table = await screen.findByRole('table', { name: 'Structure comparison' });
  expect(within(table).getAllByRole('rowheader')).toHaveLength(8);
  expect(within(table).getAllByRole('columnheader')).toHaveLength(4);
  expect(within(table).getByText('Reference', { exact: true })).toBeVisible();
  const potency = within(table).getByRole('rowheader', { name: 'IC50 原文 · nM' }).closest('tr')!;
  expect(potency).toHaveTextContent('10');
  expect(potency).toHaveTextContent('Δ -9.00');
  expect(potency).toHaveTextContent('<0.5 · >9');
  const raw = within(table).getByRole('rowheader', { name: rawContext.name }).closest('tr')!;
  expect(raw).toHaveTextContent('<6 · —');
  expect(raw).not.toHaveTextContent(/Δ|Stronger|Weaker|Indeterminate/);
  expect(
    within(table).getByRole('rowheader', { name: 'LogS' }).closest('tr'),
  ).not.toHaveTextContent('0.00');
  expect(sarStudyApi.drawing).not.toHaveBeenCalled();
});

it('uses a local automatic default but preserves explicit broader selection on locale and resize', async () => {
  const broad = {
    ...site,
    origin: 'single_site' as const,
    region: { ...site.region, id: 'a'.repeat(32), atom_indices: [0, 1, 2] },
  };
  const local = { ...broad, region: { ...broad.region, id: 'b'.repeat(32), atom_indices: [0] } };
  vi.mocked(sarStudyApi.matrix).mockImplementation(async (_job, _dataset, _reference, selections) =>
    decodeStudyMatrix({
      ...packet,
      previews: packet.previews.map((item, index) => {
        const region =
          selections[index]!.region_id === local.region.id ? local.region : broad.region;
        return { ...item, region, pair: { ...item.pair, region_id: region.id } };
      }),
    }),
  );
  const changed = {
    ...props,
    sites: [broad, local],
    siteOrder: new Map([
      [broad.region.id, 0],
      [local.region.id, 1],
    ]),
  };
  const { rerender } = render(<NetworkMatrix {...changed} />);
  expect(await screen.findByRole('combobox', { name: 'Variable regions · I-2' })).toHaveValue(
    local.region.id,
  );
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: 'Variable regions · I-2' }),
    broad.region.id,
  );
  expect(await screen.findByRole('combobox', { name: 'Variable regions · I-2' })).toHaveValue(
    broad.region.id,
  );
  vi.mocked(useMediaQuery).mockReturnValue(true);
  rerender(<NetworkMatrix {...changed} />);
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('combobox', { name: '变化区域 · I-2' })).toHaveValue(broad.region.id);
  expect(sarStudyApi.matrix).toHaveBeenCalledTimes(2);
});

it('keeps source labels and raw readings unchanged on language switch and supports direct source/pair controls', async () => {
  const original = JSON.stringify(packet);
  render(<NetworkMatrix {...props} />);
  await screen.findByRole('table', { name: 'Structure comparison' });
  await userEvent.click(screen.getByRole('button', { name: 'Compare I-2' }));
  expect(props.onCompare).toHaveBeenCalledWith(site, 'P2', expect.any(HTMLButtonElement));
  await userEvent.click(screen.getByRole('button', { name: 'Source details · I-3' }));
  expect(props.onSource).toHaveBeenCalledWith('P3');
  await act(() => setLocale('zh-CN'));
  expect(screen.getByRole('table', { name: '结构对照' })).toHaveTextContent('I-2');
  expect(screen.getByRole('rowheader', { name: rawContext.name })).toBeVisible();
  expect(sarStudyApi.matrix).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(packet)).toBe(original);
});

it('does not request a matrix while inactive, or display a result from another source/report', async () => {
  const { rerender } = render(<NetworkMatrix {...props} active={false} />);
  expect(sarStudyApi.matrix).not.toHaveBeenCalled();
  vi.mocked(sarStudyApi.matrix).mockResolvedValue({
    ...decodeStudyMatrix(packet),
    previews: decodeStudyMatrix(packet).previews.map((item) => ({
      ...item,
      job: { ...item.job, input_sha256: 'a'.repeat(64) },
    })),
  });
  rerender(<NetworkMatrix {...props} />);
  await screen.findByRole('alert');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('refuses mixed references/jobs, duplicate members, missing drawings and a greater-than-six matrix', () => {
  for (const invalid of [
    { ...packet, previews: [] },
    { ...packet, previews: Array(7).fill(packet.previews[0]) },
    { ...packet, previews: [packet.previews[0], packet.previews[0]] },
    { ...packet, previews: [packet.previews[0], { ...packet.previews[1]!, drawings: null }] },
    { ...packet, reference_drawing: { ...packet.reference_drawing, id: 'wrong' } },
    {
      ...packet,
      previews: [packet.previews[0], { ...packet.previews[1]!, job: { ...studyJob, id: 'other' } }],
    },
  ])
    expect(() => decodeStudyMatrix(invalid)).toThrow();
});

it('preserves unknown/mixed-origin property values while showing no manufactured zero or delta', async () => {
  const guarded = {
    ...packet,
    previews: packet.previews.map((item) => ({
      ...item,
      property_differences: { molecular_weight: null, Solubility_AqSolDB: null },
      property_statuses: { molecular_weight: 'origin_unknown', Solubility_AqSolDB: 'missing' },
    })),
  };
  vi.mocked(sarStudyApi.matrix).mockResolvedValue(decodeStudyMatrix(guarded));
  render(<NetworkMatrix {...props} />);
  const table = await screen.findByRole('table', { name: 'Structure comparison' });
  const row = within(table).getByRole('rowheader', { name: 'MW' }).closest('tr')!;
  expect(row).toHaveTextContent('120.00');
  expect(row).not.toHaveTextContent('Δ');
  expect(within(row).getAllByLabelText('Property origin not established')).toHaveLength(2);
  await act(() => setLocale('zh-CN'));
  expect(within(row).getAllByLabelText('性质来源未确认')).toHaveLength(2);
  for (const statuses of [
    { molecular_weight: 'origin_unknown', Solubility_AqSolDB: 'missing' },
    { molecular_weight: 'comparable', Solubility_AqSolDB: 'comparable' },
    { unexpected: 'missing' },
  ])
    expect(() =>
      decodeStudyMatrix({
        ...packet,
        previews: packet.previews.map((item) => ({
          ...item,
          property_statuses: statuses,
        })),
      }),
    ).toThrow();
});

it('renders approximate native roundoff and exact small deltas consistently without changing source data or locale identity', async () => {
  const first = 137.11,
    second = 137.11000000000004;
  const near = second - first,
    small = -5.746154 - -5.74;
  const controlled = {
    ...packet,
    previews: packet.previews.map((item) => ({
      ...item,
      reference: {
        ...item.reference,
        properties: { ...item.reference.properties, tpsa: first, Solubility_AqSolDB: -5.74 },
        property_origins: {
          ...item.reference.property_origins,
          tpsa: 'computed_rdkit',
          Solubility_AqSolDB: 'computed_rdkit',
        },
      },
      candidate: {
        ...item.candidate,
        properties: { ...item.candidate.properties, tpsa: second, Solubility_AqSolDB: -5.746154 },
        property_origins: {
          ...item.candidate.property_origins,
          tpsa: 'computed_rdkit',
          Solubility_AqSolDB: 'computed_rdkit',
        },
      },
      property_differences: { tpsa: near, Solubility_AqSolDB: small },
      property_statuses: { tpsa: 'comparable', Solubility_AqSolDB: 'comparable' },
    })),
  };
  const original = JSON.stringify(controlled);
  vi.mocked(sarStudyApi.matrix).mockResolvedValue(decodeStudyMatrix(controlled));
  render(<NetworkMatrix {...props} />);
  const table = await screen.findByRole('table', { name: 'Structure comparison' });
  expect(within(table).getAllByText('Δ ≈ 0')).toHaveLength(2);
  expect(within(table).getAllByText('Δ -0.00615')).toHaveLength(2);
  expect(within(table).getAllByTitle('Raw difference: +' + String(near))).toHaveLength(2);
  await act(() => setLocale('zh-CN'));
  expect(within(table).getAllByTitle('原始差值: +' + String(near))).toHaveLength(2);
  expect(within(table).getAllByText('Δ ≈ 0')).toHaveLength(2);
  expect(sarStudyApi.matrix).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(controlled)).toBe(original);
});

it('uses one exact ordered read with shared authentication and rejects wrong selectors without a write', async () => {
  const transport = vi.fn<typeof fetch>(async (url) =>
    json(String(url).endsWith('/session') ? session : packet),
  );
  const api = createSARStudyApi(new ApiClient(transport));
  const signal = new AbortController().signal;
  const selections = rows.map((row) => ({
    region_id: site.region.id,
    molecule_id: row.molecule_id,
  }));
  await api.matrix(studyJob.id, studyReport.dataset_id, studyRow.molecule_id, selections, signal);
  const call = transport.mock.calls.at(-1)!;
  const query = new URL(String(call[0]), 'http://localhost').searchParams;
  expect(query.getAll('molecule_id')).toEqual(rows.map((row) => row.molecule_id));
  expect(query.getAll('region_id')).toEqual([site.region.id, site.region.id]);
  expect(transport.mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true);
  await expect(
    api.matrix(studyJob.id, studyReport.dataset_id, 'wrong', selections, signal),
  ).rejects.toThrow();
  expect(() =>
    api.matrix(studyJob.id, studyReport.dataset_id, studyRow.molecule_id, [], signal),
  ).toThrow();
});
