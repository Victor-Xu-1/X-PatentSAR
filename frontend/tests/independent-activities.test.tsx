import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ActivityColumn } from '../src/api/types';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { compound } from './fixtures';

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
const columns: ActivityColumn[] = [
  { id: 'a'.repeat(64), name: 'IC50', unit: 'nM', target: 'Target A', assay: 'Binding' },
  { id: 'b'.repeat(64), name: 'IC50', unit: 'µM', target: 'Target B', assay: 'Cell assay' },
  {
    id: 'c'.repeat(64),
    name: 'Degradation grade',
    unit: null,
    target: 'Target A',
    assay: 'Western blot',
  },
];
describe('one observation context per independently resizable activity column', () => {
  it('separates same-name measurements by unit/target/assay and keeps actual sources', async () => {
    const props = callbacks();
    const values = [
      { ...compound.activities[0]!, ...columns[0]!, value: 0, page: 7 },
      { ...compound.activities[0]!, ...columns[1]!, value: 20, page: 8 },
      { ...compound.activities[0]!, ...columns[2]!, value: '+++', page: 9 },
    ];
    const row = { ...compound, activities: values };
    render(<ResultsTable {...props} rows={[row]} activityColumns={columns} />);
    expect(screen.queryByRole('columnheader', { name: /^专利活性$/ })).not.toBeInTheDocument();
    const cells = document.querySelectorAll('td.activity-value-column');
    expect(cells).toHaveLength(3);
    expect(cells[0]).toHaveTextContent('0 nM');
    expect(cells[1]).toHaveTextContent('20 µM');
    expect(cells[2]).toHaveTextContent('+++');
    await userEvent.click(within(cells[1] as HTMLElement).getByRole('button'));
    expect(props.onActivitySource).toHaveBeenCalledExactlyOnceWith(row, values[1], undefined);
    expect(screen.getAllByRole('slider')).toHaveLength(14);
    expect(screen.getByRole('table')).toHaveStyle({ tableLayout: 'fixed' });
  });
  it('keeps the complete catalog on another page, retaining repeated values instead of averaging', () => {
    const row = {
      ...compound,
      activities: [
        { ...compound.activities[0]!, ...columns[0]!, value: 12, page: 3 },
        { ...compound.activities[0]!, ...columns[0]!, value: 18, page: 4 },
      ],
    };
    const props = callbacks();
    const { rerender } = render(<ResultsTable {...props} rows={[row]} activityColumns={columns} />);
    expect(document.querySelectorAll('td.activity-value-column')[0]).toHaveTextContent(
      '12 nM18 nM',
    );
    rerender(
      <ResultsTable
        {...props}
        rows={[{ ...compound, id: 'page-two', activities: [] }]}
        activityColumns={columns}
      />,
    );
    expect(document.querySelectorAll('th.activity-value-column')).toHaveLength(3);
    expect(document.querySelectorAll('td.activity-value-column')).toHaveLength(3);
    expect(screen.getAllByRole('columnheader')).toHaveLength(14);
  });
  it('lets hidden columns return with their width while identity stays frozen', async () => {
    const props = callbacks();
    const { rerender } = render(
      <ResultsTable
        {...props}
        rows={[compound]}
        activityColumns={columns}
        metrics={['IC50', 'Degradation grade']}
      />,
    );
    const handle = screen.getByRole('slider', { name: /调整IC50.*Target A/ });
    handle.focus();
    await userEvent.keyboard('{ArrowRight}');
    const width = handle.getAttribute('aria-valuenow');
    rerender(
      <ResultsTable
        {...props}
        rows={[compound]}
        activityColumns={columns}
        metrics={['Degradation grade']}
      />,
    );
    expect(screen.queryByRole('slider', { name: /调整IC50.*Target A/ })).not.toBeInTheDocument();
    rerender(
      <ResultsTable
        {...props}
        rows={[compound]}
        activityColumns={columns}
        metrics={['IC50', 'Degradation grade']}
      />,
    );
    expect(screen.getByRole('slider', { name: /调整IC50.*Target A/ })).toHaveAttribute(
      'aria-valuenow',
      width,
    );
    expect(document.querySelectorAll('.results-table thead .frozen-column')).toHaveLength(4);
    expect(document.querySelectorAll('.results-table tbody .frozen-column')).toHaveLength(4);
    const scroller = screen.getByRole('region', { name: '可横向滚动的化合物结果表格' });
    expect(scroller.style.getPropertyValue('--frozen-leading-width')).toBe('270px');
    expect(scroller.style.getPropertyValue('--frozen-trailing-width')).toBe('48px');
    screen.getByRole('slider', { name: '调整原文编号列宽' }).focus();
    await userEvent.keyboard('{Home}');
    expect(scroller.style.getPropertyValue('--frozen-compound-width')).toBe('88px');
    expect(scroller.style.getPropertyValue('--frozen-leading-width')).toBe('238px');
    screen.getByRole('slider', { name: '调整结构列宽' }).focus();
    await userEvent.keyboard('{Home}');
    expect(scroller.style.getPropertyValue('--frozen-leading-width')).toBe('214px');
  });
});
