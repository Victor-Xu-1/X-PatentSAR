import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { decodeCompound, decodeResults } from '../src/api/decoders';
import { decodeLeadAssessment } from '../src/api/leadDecoders';
import type { LeadAssessment } from '../src/api/leadTypes';
import { leadStatuses } from '../src/api/leadTypes';
import type { Compound } from '../src/api/types';
import { ContractError } from '../src/api/validation';
import { LeadCell } from '../src/features/results/LeadCell';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { columnCanFilter, columnCanSort, defaultColumnKind } from '../src/model/columnFilters';
import { leadColumnValue, resultColumns } from '../src/model/resultColumns';
import { tableCopyText } from '../src/model/tableCopy';
import { compound, project, results } from './fixtures';
import { filterValuesFixture } from './filter-value-fixtures';

// Synthetic contract values only; these tests do not nominate patent Leads.
const assessment: LeadAssessment = {
  status: 'selected',
  rank: 1,
  score: 84.75,
  activity_coverage: 0.75,
  components: { potency: 91, coverage: 75, physchem: 80, admet: 70, diversity: 90 },
  reasons: ['覆盖三个可比活性指标', '优先级兼顾结构多样性'],
  warnings: ['ADMET 是研究预测，并非实验安全性结论'],
  scaffold: 'c1ccccc1',
  nearest_similarity: 0.35,
  policy_version: '1',
  review_only: true,
};
const rows: Compound[] = [
  { ...compound, id: 'controlled-2', display_id: 'Compound 2', lead: { ...assessment, rank: 2 } },
  { ...compound, id: 'controlled-1', display_id: 'Compound 1', lead: assessment },
  {
    ...compound,
    id: 'controlled-3',
    display_id: 'Compound 3',
    lead: { ...assessment, status: 'not_selected', rank: null },
  },
  {
    ...compound,
    id: 'controlled-4',
    display_id: 'Compound 4',
    lead: { ...assessment, status: 'stale', rank: null, score: null },
  },
];
const callbacks = () => ({
  selected: new Set<string>(),
  focusedId: null,
  onSelect: vi.fn(),
  onSelectPage: vi.fn(),
  onJump: vi.fn(),
  onActivitySource: vi.fn(),
  onCrop: vi.fn(),
  onReview: vi.fn(),
});
const filters = { q: '', target: '', confidence: '', review: '', page: 3, page_size: 25 };
const paneProps = () => ({
  ...callbacks(),
  project,
  filters,
  onFilters: vi.fn(),
  onExport: vi.fn(),
  onUpload: vi.fn(),
  resource: {
    data: { ...results, items: rows, total: 4, page: 1, page_size: 25 },
    loading: false,
    error: null,
    reload: vi.fn(),
  },
});

describe('strict additive Lead assessment contract', () => {
  it('rejects unbounded or unknown components and inconsistent selection identity', () => {
    for (const value of [
      { ...assessment, score: null },
      { ...assessment, status: 'not_selected', rank: 1 },
      { ...assessment, components: { unverified: 90 } },
      { ...assessment, reasons: [''] },
      { ...assessment, reasons: ['unsafe\nmessage'] },
    ])
      expect(() => decodeLeadAssessment(value)).toThrow(ContractError);
  });
  it('keeps older Compound/Results packets without a Lead field compatible', () => {
    expect(decodeCompound(compound)).not.toHaveProperty('lead');
    expect(decodeCompound({ ...compound, lead: null }).lead).toBeNull();
    expect(decodeResults(results).items[0]).not.toHaveProperty('lead');
    expect(decodeCompound({ ...compound, lead: assessment }).lead).toEqual(assessment);
  });

  it.each(leadStatuses)('accepts the explicitly supplied lifecycle state %s', (status) => {
    const value = { ...assessment, status, rank: status === 'selected' ? 8 : null };
    expect(decodeLeadAssessment(value)).toEqual(value);
  });

  it.each(Object.keys(assessment))('rejects a present packet missing required %s', (key) => {
    const missing: Record<string, unknown> = { ...assessment };
    delete missing[key];
    expect(() => decodeLeadAssessment(missing)).toThrow(ContractError);
    expect(() => decodeLeadAssessment({ ...assessment, [key]: undefined })).toThrow(ContractError);
  });

  it.each([
    ['status', 'experimental_lead'],
    ['rank', null],
    ['rank', 0],
    ['rank', 11],
    ['rank', 1.5],
    ['rank', '1'],
    ['rank', true],
    ['score', -0.1],
    ['score', 100.1],
    ['score', Infinity],
    ['score', NaN],
    ['score', '84.75'],
    ['activity_coverage', -0.01],
    ['activity_coverage', 1.01],
    ['activity_coverage', '0.75'],
    ['nearest_similarity', -0.01],
    ['nearest_similarity', 1.01],
    ['nearest_similarity', Infinity],
    ['components', null],
    ['components', []],
    ['components', { potency: -1 }],
    ['components', { potency: 101 }],
    ['components', { potency: '91' }],
    ['components', { potency: NaN }],
    ['reasons', Array.from({ length: 13 }, () => 'reason')],
    ['reasons', ['r'.repeat(301)]],
    ['reasons', [1]],
    ['warnings', Array.from({ length: 13 }, () => 'warning')],
    ['warnings', ['w'.repeat(301)]],
    ['warnings', 'warning'],
    ['scaffold', 'c'.repeat(2049)],
    ['scaffold', 1],
    ['policy_version', '3'],
    ['policy_version', 1],
    ['review_only', false],
    ['review_only', 'true'],
  ])('rejects malformed/out-of-bound %s without coercion', (key, value) => {
    expect(() => decodeLeadAssessment({ ...assessment, [key as string]: value })).toThrow(
      ContractError,
    );
  });

  it('accepts finite endpoints and bounded Unicode without inventing missing nullable fields', () => {
    expect(
      decodeLeadAssessment({
        ...assessment,
        rank: 10,
        score: 0,
        activity_coverage: 1,
        components: { potency: 0, coverage: 100 },
        reasons: Array.from({ length: 12 }, () => '🧪'.repeat(300)),
        warnings: [],
        nearest_similarity: 0,
        scaffold: null,
      }),
    ).toMatchObject({ rank: 10, score: 0, nearest_similarity: 0, scaffold: null });
    expect(
      decodeLeadAssessment({ ...assessment, status: 'unranked', rank: null, score: null }),
    ).toMatchObject({ rank: null, score: null });
    expect(() =>
      decodeResults({ ...results, items: [{ ...compound, lead: { status: 'selected' } }] }),
    ).toThrow(ContractError);
  });
});

describe('minimal backend-owned Lead column', () => {
  it('shows policy-two model-risk candidates as review-required without calling them safe', () => {
    const value = { ...assessment, policy_version: '2', risk_review_required: true };
    const decoded = decodeLeadAssessment(value);
    render(
      <table>
        <tbody>
          <tr>
            <LeadCell assessment={decoded} />
          </tr>
        </tbody>
      </table>,
    );
    expect(screen.getByText('Lead 1')).toHaveClass('lead-risk-review');
    expect(screen.getByText('Lead 1').closest('td')).toHaveAttribute(
      'title',
      expect.stringContaining('高模型风险待复核'),
    );
    expect(() => decodeLeadAssessment({ ...value, risk_review_required: 'true' })).toThrow(
      ContractError,
    );
    const { risk_review_required: _risk, ...incomplete } = value;
    expect(() => decodeLeadAssessment(incomplete)).toThrow(ContractError);
  });
  it('places a centered Lead label after Compound and structure without reordering rows', () => {
    render(<ResultsTable {...callbacks()} rows={rows} />);
    expect(
      screen
        .getAllByRole('columnheader')
        .slice(0, 4)
        .map((header) => header.dataset.column),
    ).toEqual(['select', 'compound', 'structure', 'lead']);
    const tableRows = document.querySelectorAll<HTMLTableRowElement>('tbody tr');
    expect(Array.from(tableRows).map((row) => row.dataset.compound)).toEqual(
      rows.map((row) => row.id),
    );
    expect(tableRows[0]!.querySelector('td[data-column="lead"]')).toHaveTextContent('Lead 2');
    expect(tableRows[1]!.querySelector('td[data-column="lead"]')).toHaveTextContent('Lead 1');
    expect(tableRows[2]!.querySelector('td[data-column="lead"]')).toHaveTextContent('—');
    expect(tableRows[3]!.querySelector('td[data-column="lead"]')).toHaveTextContent('待更新');
    const lead = screen.getByText('Lead 1').closest('td')!;
    expect(lead).toHaveClass('lead-column');
    expect(lead.title).toContain('候选优先级 84.8 / 100');
    expect(lead.title).toContain('活性覆盖 75%');
    expect(lead.title).toContain(assessment.reasons[0]);
    expect(lead.title).toContain(assessment.warnings[0]);
    expect(lead.title).toContain('不代表实验验证');
    expect(screen.queryByText(/候选优先级/)).not.toBeInTheDocument();
  });

  it.each(['not_run', 'not_selected', 'ineligible', 'unranked', 'stale'] as const)(
    'never shows a historical/supplied rank as selected for %s',
    (status) => {
      render(
        <table>
          <tbody>
            <tr>
              <LeadCell assessment={{ ...assessment, status }} />
            </tr>
          </tbody>
        </table>,
      );
      expect(screen.queryByText('Lead 1')).not.toBeInTheDocument();
      expect(leadColumnValue({ ...assessment, status })).toBe('');
    },
  );

  it('shows an honest missing state and renders untrusted reasons only as plain title text', () => {
    const { rerender } = render(<ResultsTable {...callbacks()} rows={[compound]} />);
    const missing = document.querySelector('td[data-column="lead"]')!;
    expect(missing).toHaveTextContent('—');
    expect(missing).toHaveAttribute('data-lead-status', 'not_run');
    const reason = '<img src="untrusted" onerror="alert(1)">';
    rerender(
      <ResultsTable
        {...callbacks()}
        rows={[{ ...compound, lead: { ...assessment, reasons: [reason] } }]}
      />,
    );
    expect(document.querySelector('td[data-column="lead"]')!.getAttribute('title')).toContain(
      reason,
    );
    expect(document.querySelector('img[src="untrusted"]')).toBeNull();
  });

  it('retains the same row identity for source, crop, correction and selection', async () => {
    const props = callbacks();
    render(<ResultsTable {...props} rows={[rows[0]!]} />);
    await userEvent.click(screen.getByLabelText('选择化合物 Compound 2'));
    await userEvent.click(screen.getByLabelText('查看 Compound 2 结构详情'));
    await userEvent.click(screen.getByLabelText('修正 Compound 2'));
    await userEvent.click(screen.getByLabelText(/Compound 2 结构来源/));
    expect(props.onSelect).toHaveBeenCalledExactlyOnceWith(rows[0]!.id);
    expect(props.onCrop).toHaveBeenCalledExactlyOnceWith(rows[0]);
    expect(props.onReview).toHaveBeenCalledExactlyOnceWith(rows[0]);
    expect(props.onJump).toHaveBeenCalledExactlyOnceWith(rows[0]);
  });

  it('supports the existing Lead column hide/restore and keyboard width controls', async () => {
    render(<ResultsPane {...paneProps()} />);
    const user = userEvent.setup();
    const slider = screen.getByRole('slider', { name: '调整Lead列宽' });
    slider.focus();
    await user.keyboard('{ArrowRight}');
    expect(slider).toHaveAttribute('aria-valuenow', '96');
    await user.click(screen.getByRole('button', { name: 'Lead 列选项' }));
    await user.click(screen.getByRole('button', { name: '隐藏此列' }));
    expect(screen.queryByRole('columnheader', { name: 'Lead' })).not.toBeInTheDocument();
    expect(document.querySelector('td[data-column="lead"]')).toBeNull();
    await user.click(screen.getByRole('button', { name: '显示列' }));
    await user.click(screen.getByLabelText('显示列 Lead'));
    expect(screen.getByRole('columnheader', { name: 'Lead' })).toBeVisible();
    expect(screen.getByRole('slider', { name: '调整Lead列宽' })).toHaveAttribute(
      'aria-valuenow',
      '96',
    );
    expect(screen.getByText('Lead 1')).toBeVisible();
  });

  it('uses server Lead choices and sends full-project sort/filter without local ranking', async () => {
    const choices = vi
      .spyOn(api, 'filterValues')
      .mockResolvedValue(filterValuesFixture('lead', ['Lead 1', 'Lead 2']));
    const props = paneProps();
    render(<ResultsPane {...props} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Lead 列选项' }));
    expect(await screen.findByLabelText('筛选值 Lead 1')).toBeVisible();
    expect(choices).toHaveBeenCalledWith(
      project.id,
      'lead',
      expect.objectContaining({ q: '' }),
      '',
      1,
      expect.any(AbortSignal),
    );
    expect(screen.queryByRole('button', { name: '按颜色筛选' })).not.toBeInTheDocument();
    await user.click(screen.getByLabelText('全选筛选取值'));
    await user.click(screen.getByLabelText('筛选值 Lead 1'));
    await user.click(screen.getByRole('button', { name: '确定' }));
    expect(props.onFilters).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'lead', op: 'in', values: ['Lead 1'], include_empty: false }],
    });
    await user.click(screen.getByRole('button', { name: 'Lead 列选项' }));
    await user.click(screen.getByRole('button', { name: '升序' }));
    expect(props.onFilters).toHaveBeenLastCalledWith({
      sort_column: 'lead',
      sort_direction: 'asc',
      sort_band: '',
      page: 1,
    });
    expect(
      Array.from(document.querySelectorAll<HTMLTableRowElement>('tbody tr')).map(
        (row) => row.dataset.compound,
      ),
    ).toEqual(rows.map((row) => row.id));
    choices.mockRestore();
  });

  it('retains Lead controls through empty/error/loading states without implying selection', () => {
    const props = paneProps();
    const { rerender } = render(
      <ResultsPane
        {...props}
        resource={{ ...props.resource, data: { ...props.resource.data, items: [], total: 0 } }}
      />,
    );
    expect(screen.getByRole('columnheader', { name: 'Lead' })).toBeVisible();
    expect(screen.getByText('暂无匹配的提取结果')).toBeVisible();
    expect(screen.queryByText('Lead 1')).not.toBeInTheDocument();
    rerender(
      <ResultsPane {...props} resource={{ ...props.resource, data: null, loading: true }} />,
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('Lead 1')).not.toBeInTheDocument();
    rerender(
      <ResultsPane
        {...props}
        resource={{ ...props.resource, data: null, error: new Error('Lead query rejected') }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Lead query rejected');
    expect(screen.getByRole('button', { name: '复制当前页' })).toBeDisabled();
  });

  it('copies selected Lead labels only in visible columns, treating absent/expired values as true blanks', () => {
    const headers = resultColumns().filter((column) => ['compound', 'lead'].includes(column.id));
    const snapshot = JSON.stringify(rows);
    expect(tableCopyText(rows, headers, [])).toBe(
      'Compound\tLead\nCompound 2\tLead 2\nCompound 1\tLead 1\nCompound 3\t\nCompound 4\t',
    );
    expect(
      tableCopyText(
        rows,
        headers.filter((column) => column.id !== 'lead'),
        [],
      ),
    ).not.toContain('Lead');
    expect(JSON.stringify(rows)).toBe(snapshot);
    const lead = headers.find((column) => column.id === 'lead')!;
    expect(columnCanFilter(lead)).toBe(true);
    expect(columnCanSort(lead)).toBe(true);
    expect(defaultColumnKind(lead)).toBe('text');
  });

  it('never copies rank or score from a malformed unvalidated selection as a Lead label', () => {
    expect(leadColumnValue({ ...assessment, rank: null })).toBe('');
    expect(leadColumnValue({ ...assessment, rank: 11 })).toBe('');
    expect(leadColumnValue({ ...assessment, rank: 1.5 })).toBe('');
    render(
      <ResultsTable
        {...callbacks()}
        rows={[{ ...compound, lead: { ...assessment, rank: null } }]}
      />,
    );
    expect(document.querySelector('td[data-column="lead"]')).toHaveTextContent('—');
  });
});
