import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultsPane } from '../src/features/results/ResultsPane';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { resultColumns } from '../src/model/resultColumns';
import { tableActivityColumns } from '../src/model/activityColumns';
import { safeTsvCell, tableCopyText } from '../src/model/tableCopy';
import { compound, project, results } from './fixtures';

const activity = compound.activities[0]!;
const catalog = [
  {
    id: 'a'.repeat(64),
    ...activity,
    filter_values: [
      { value: '++', count: 20 },
      { value: '+', count: 10 },
    ],
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
const baseFilters = { q: '', target: '', confidence: '', review: '', page: 3, page_size: 10 };
const paneProps = () => ({
  ...callbacks(),
  project,
  filters: baseFilters,
  onFilters: vi.fn(),
  onExport: vi.fn(),
  onUpload: vi.fn(),
  resource: {
    data: { ...results, items: [compound], activity_columns: catalog },
    loading: false,
    error: null,
    reload: vi.fn(),
  },
});

describe('Excel-like columns use one full-project server query', () => {
  it('hides and restores every column, independently of same-name activity contexts', async () => {
    render(<ResultsPane {...paneProps()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Compound 列选项' }));
    await user.click(screen.getByRole('button', { name: '隐藏此列' }));
    expect(screen.queryByRole('columnheader', { name: 'Compound' })).not.toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '结构' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: '显示列' }));
    await user.click(screen.getByLabelText('显示列 Compound'));
    await user.click(screen.getByLabelText('显示列 MW'));
    expect(screen.getByRole('columnheader', { name: 'Compound' })).toBeVisible();
    expect(screen.queryByRole('columnheader', { name: 'MW' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '显示全部列' }));
    expect(screen.getByRole('columnheader', { name: 'MW' })).toBeVisible();
  });

  it('sorts through the backend, never reorders the current-page rows locally', async () => {
    const props = paneProps();
    render(<ResultsPane {...props} />);
    await userEvent.click(screen.getByRole('button', { name: 'Compound 列选项' }));
    await userEvent.click(screen.getByRole('button', { name: '升序' }));
    expect(props.onFilters).toHaveBeenCalledExactlyOnceWith({
      sort_column: 'compound',
      sort_direction: 'asc',
      page: 1,
    });
    expect(document.querySelector('tbody tr')).toHaveAttribute('data-compound', compound.id);
  });
  it('independently hides exact same-name experimental columns without changing row selection', async () => {
    const props = paneProps();
    const second = { ...catalog[0]!, id: 'b'.repeat(64), target: '另一靶点' };
    render(
      <ResultsPane
        {...props}
        selected={new Set([compound.id])}
        resource={{
          ...props.resource,
          data: { ...props.resource.data, activity_columns: [...catalog, second] },
        }}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '显示列' }));
    await userEvent.click(
      screen.getByLabelText(`显示列 抑制等级 · ${activity.target} · ${activity.assay}`),
    );
    expect(document.querySelector(`th[data-column="activity:${catalog[0]!.id}"]`)).toBeNull();
    expect(document.querySelector(`th[data-column="activity:${second.id}"]`)).not.toBeNull();
    expect(screen.getByLabelText('选择化合物 I-7')).toBeChecked();
    expect(props.onFilters).not.toHaveBeenCalled();
  });
  it('can hide all columns, including utility controls, and recover without losing the original data', async () => {
    const props = paneProps();
    render(<ResultsPane {...props} />);
    await userEvent.click(screen.getByRole('button', { name: '显示列' }));
    const dialog = screen.getByRole('dialog', { name: '显示列' });
    for (const checkbox of within(dialog).getAllByRole('checkbox')) await userEvent.click(checkbox);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('所有列已隐藏')).toBeVisible();
    await userEvent.click(within(dialog).getByRole('button', { name: '显示全部列' }));
    expect(screen.getByRole('table')).toBeVisible();
    expect(screen.getByLabelText('选择化合物 I-7')).toBeEnabled();
    expect(props.onFilters).not.toHaveBeenCalled();
  });
  it('restores indeterminate selection and retained widths when a utility column is restored', async () => {
    const props = callbacks();
    const rows = [compound, { ...compound, id: 'I-8', display_id: 'I-8' }];
    const { rerender } = render(
      <ResultsTable {...props} selected={new Set([compound.id])} rows={rows} />,
    );
    const resize = screen.getByRole('slider', { name: '调整结构列宽' });
    resize.focus();
    await userEvent.keyboard('{ArrowRight}');
    rerender(
      <ResultsTable
        {...props}
        selected={new Set([compound.id])}
        rows={rows}
        hiddenColumns={['select', 'structure']}
      />,
    );
    rerender(<ResultsTable {...props} selected={new Set([compound.id])} rows={rows} />);
    expect((screen.getByLabelText('选择当前页全部化合物') as HTMLInputElement).indeterminate).toBe(
      true,
    );
    expect(screen.getByRole('slider', { name: '调整结构列宽' })).toHaveAttribute(
      'aria-valuenow',
      '104',
    );
  });

  it('shows unfiltered project-wide value choices and preserves other column conditions', async () => {
    const props = paneProps();
    const filters = {
      ...baseFilters,
      column_filters: [{ column: 'compound', op: 'contains' as const, value: 'I' }],
    };
    render(<ResultsPane {...props} filters={filters} />);
    await userEvent.click(
      screen.getByRole('button', {
        name: `抑制等级 · ${activity.target} · ${activity.assay} 列选项`,
      }),
    );
    await userEvent.selectOptions(screen.getByLabelText('筛选方式'), 'in');
    expect(screen.getByLabelText('筛选值 +')).toBeVisible();
    expect(screen.getByText('10')).toBeVisible();
    await userEvent.click(screen.getByLabelText('筛选值 +'));
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }));
    expect(props.onFilters).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [
        ...filters.column_filters,
        { column: `activity:${catalog[0]!.id}`, op: 'in', values: ['+'] },
      ],
    });
  });

  it('sends bounded numeric ranges and keeps invalid values from becoming a silent query', async () => {
    const props = paneProps();
    render(<ResultsPane {...props} />);
    await userEvent.click(screen.getByRole('button', { name: 'MW 列选项' }));
    await userEvent.selectOptions(screen.getByLabelText('筛选方式'), 'range');
    fireEvent.change(screen.getByLabelText('筛选下限'), { target: { value: '500' } });
    fireEvent.change(screen.getByLabelText('筛选上限'), { target: { value: '300' } });
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }));
    expect(screen.getByRole('alert')).toHaveTextContent('下限');
    expect(props.onFilters).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('筛选上限'), { target: { value: '800' } });
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }));
    expect(props.onFilters).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [
        { column: 'property:molecular_weight', op: 'gte', value: '500' },
        { column: 'property:molecular_weight', op: 'lte', value: '800' },
      ],
    });
  });

  it('remaps frozen offsets when identity, selection and correction columns are hidden', () => {
    const props = callbacks();
    const { rerender } = render(
      <ResultsTable {...props} rows={[compound]} hiddenColumns={['select', 'compound', 'edit']} />,
    );
    const region = screen.getByLabelText('可横向滚动的化合物结果表格');
    expect(region.style.getPropertyValue('--frozen-select-width')).toBe('0px');
    expect(region.style.getPropertyValue('--frozen-compound-width')).toBe('0px');
    expect(region.style.getPropertyValue('--frozen-leading-width')).toBe('96px');
    expect(region.style.getPropertyValue('--frozen-trailing-width')).toBe('0px');
    expect(within(screen.getAllByRole('row')[1]!).getAllByRole('cell')).toHaveLength(
      screen.getAllByRole('columnheader').length,
    );
    rerender(<ResultsTable {...props} rows={[compound]} hiddenColumns={['structure']} />);
    expect(region.style.getPropertyValue('--frozen-leading-width')).toBe('138px');
    expect(screen.getByLabelText('选择化合物 I-7')).toBeEnabled();
  });

  it('retains filter controls even when the server returns no matching rows', async () => {
    const props = paneProps();
    render(
      <ResultsPane
        {...props}
        filters={{
          ...baseFilters,
          column_filters: [{ column: 'compound', op: 'eq', value: 'missing' }],
        }}
        resource={{ ...props.resource, data: { ...props.resource.data, items: [], total: 0 } }}
      />,
    );
    expect(screen.getByText('暂无匹配的提取结果')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Compound 列选项' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '清除列筛选' }));
    expect(props.onFilters).toHaveBeenCalledWith({ column_filters: [], page: 1 });
  });
  it('keeps resized widths through loading, failed queries, empty results and all-hidden recovery', async () => {
    const props = paneProps();
    const { rerender } = render(<ResultsPane {...props} />);
    const slider = screen.getByRole('slider', { name: '调整Compound列宽' });
    slider.focus();
    await userEvent.keyboard('{ArrowRight}');
    rerender(
      <ResultsPane {...props} resource={{ ...props.resource, data: null, loading: true }} />,
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    rerender(
      <ResultsPane
        {...props}
        resource={{ ...props.resource, data: null, error: new Error('column query rejected') }}
        filters={{
          ...baseFilters,
          column_filters: [{ column: 'unknown', op: 'eq', value: '1' }],
          sort_column: 'unknown',
          sort_direction: 'asc',
        }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('column query rejected');
    await userEvent.click(screen.getByRole('button', { name: '清除列筛选' }));
    await userEvent.click(screen.getByRole('button', { name: '取消列排序' }));
    expect(props.onFilters.mock.calls).toEqual([
      [{ column_filters: [], page: 1 }],
      [{ sort_column: '', sort_direction: 'asc', page: 1 }],
    ]);
    rerender(
      <ResultsPane
        {...props}
        resource={{ ...props.resource, data: { ...props.resource.data, items: [], total: 0 } }}
      />,
    );
    expect(screen.getByRole('slider', { name: '调整Compound列宽' })).toHaveAttribute(
      'aria-valuenow',
      '108',
    );
    await userEvent.click(screen.getByRole('button', { name: '显示列' }));
    const dialog = screen.getByRole('dialog', { name: '显示列' });
    for (const checkbox of within(dialog).getAllByRole('checkbox')) await userEvent.click(checkbox);
    expect(screen.getByText('所有列已隐藏')).toBeVisible();
    await userEvent.click(within(dialog).getByRole('button', { name: '显示全部列' }));
    await userEvent.click(screen.getByRole('button', { name: '关闭对话框' }));
    rerender(<ResultsPane {...props} />);
    expect(screen.getByRole('slider', { name: '调整Compound列宽' })).toHaveAttribute(
      'aria-valuenow',
      '108',
    );
  });
});

describe('safe TSV copy is explicitly a current visible-page operation', () => {
  it.each(['=SUM(A1)', '+cmd', '-cmd', '@cmd', '\t=SUM(A1)', '\uFEFF=SUM(A1)'])(
    'neutralizes the spreadsheet formula prefix %s',
    (value) => {
      expect(safeTsvCell(value)).toMatch(/^'/);
      expect(safeTsvCell(value)).not.toMatch(/[\t\r\n]/);
    },
  );
  it('does not copy hidden columns or missing/stale computed values as numbers', () => {
    const text = tableCopyText(
      [compound],
      resultColumns().filter(
        (column) => column.id === 'compound' || column.id === 'property:molecular_weight',
      ),
      [],
    );
    expect(text).toBe('Compound\tMW\nI-7\t');
    expect(text).not.toContain('++');
  });
  it('copies the current page in source order after a user gesture and announces its exact scope', async () => {
    const props = paneProps();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<ResultsPane {...props} />);
    expect(writeText).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '复制当前页' }));
    expect(writeText).toHaveBeenCalledOnce();
    expect(screen.getByRole('status')).toHaveTextContent('已复制当前页 1 行（可见列）');
  });
  it('preserves repeated observations and full precision, while neutralizing formula text without mutating input', () => {
    const row = {
      ...compound,
      display_id: ' =HYPERLINK("evil")',
      activities: [
        { ...activity, value: '++' },
        { ...activity, value: '@attack\tline\nnext' },
      ],
    };
    const snapshot = JSON.stringify(row);
    const activities = tableActivityColumns(catalog, [activity.name]);
    const columns = resultColumns(activities).filter((column) =>
      ['compound', `activity:${catalog[0]!.id}`].includes(column.id),
    );
    const text = tableCopyText([row], columns, activities);
    expect(text.split('\n')).toHaveLength(2);
    expect(text).toContain("' =HYPERLINK");
    expect(text).toContain("'++ | @attack line next");
    expect(JSON.stringify(row)).toBe(snapshot);
  });

  it('copies only selected rows on this page and offers a keyboard fallback on clipboard failure', async () => {
    const props = paneProps();
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard denied'));
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<ResultsPane {...props} selected={new Set([compound.id, 'not-on-this-page'])} />);
    await userEvent.click(screen.getByRole('button', { name: '复制当前页所选行 (1)' }));
    expect(writeText).toHaveBeenCalledOnce();
    const dialog = screen.getByRole('dialog', { name: '复制当前页所选行' });
    expect(
      (within(dialog).getByRole('textbox', { name: '可手动复制的 TSV' }) as HTMLTextAreaElement)
        .value,
    ).toContain(compound.display_id);
    expect(
      (
        within(dialog).getByRole('textbox', { name: '可手动复制的 TSV' }) as HTMLTextAreaElement
      ).value.split('\n'),
    ).toHaveLength(2);
    expect(dialog).toHaveTextContent('仅当前页');
  });
});
