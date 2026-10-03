import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { compound } from './fixtures';

function tableProps() {
  return {
    rows: [compound],
    offset: 0,
    selected: new Set([compound.id]),
    focusedId: null,
    metrics: ['抑制等级'],
    onSelect: vi.fn(),
    onSelectPage: vi.fn(),
    onJump: vi.fn(),
    onActivitySource: vi.fn(),
    onCrop: vi.fn(),
    onReview: vi.fn(),
  };
}

describe('result column width changes preserve real row behavior', () => {
  it('resizes every header, respects bounds and resets without changing selection', async () => {
    const props = tableProps();
    render(<ResultsTable {...props} />);
    expect(screen.getAllByRole('slider')).toHaveLength(screen.getAllByRole('columnheader').length);
    const resize = screen.getByRole('slider', { name: '调整原始结构 / 编号列宽' });
    const table = screen.getByRole('table');
    resize.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(resize).toHaveAttribute('aria-valuenow', '150');
    expect(table).toHaveClass('columns-resized');
    await userEvent.keyboard('{Home}');
    expect(resize).toHaveAttribute('aria-valuenow', '142');
    await userEvent.keyboard('{End}');
    expect(resize).toHaveAttribute('aria-valuenow', '480');
    fireEvent.doubleClick(resize);
    expect(resize).toHaveAttribute('aria-valuenow', '142');
    expect(screen.getByLabelText(`选择化合物 ${compound.display_id}`)).toBeChecked();
    expect(screen.getByTitle('抑制等级 = ++')).toBeVisible();
    expect(props.onSelect).not.toHaveBeenCalled();
    expect(props.onSelectPage).not.toHaveBeenCalled();
  });
  it('starts at measured width and cancels back to the original table', () => {
    const props = tableProps();
    render(<ResultsTable {...props} />);
    const header = screen.getByRole('columnheader', { name: '原始结构 / 编号' });
    vi.spyOn(header, 'getBoundingClientRect').mockReturnValue({ width: 200 } as DOMRect);
    const resize = screen.getByRole('slider', { name: '调整原始结构 / 编号列宽' });
    fireEvent.pointerDown(resize, { pointerId: 1, button: 0, clientX: 200, isPrimary: true });
    fireEvent.pointerMove(resize, { pointerId: 1, clientX: 290 });
    expect(resize).toHaveAttribute('aria-valuenow', '290');
    fireEvent.keyDown(resize, { key: 'Escape' });
    fireEvent.pointerUp(resize, { pointerId: 1 });
    expect(screen.getByRole('table')).not.toHaveClass('columns-resized');
    expect(resize).toHaveAttribute('aria-valuenow', '142');
    expect(props.onSelect).not.toHaveBeenCalled();
  });
  it('retains widths across pages and metric hiding without changing source navigation', async () => {
    const props = tableProps();
    const { rerender } = render(<ResultsTable {...props} />);
    const resize = screen.getByRole('slider', { name: '调整抑制等级列宽' });
    resize.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(resize).toHaveAttribute('aria-valuenow', '136');
    rerender(<ResultsTable {...props} metrics={[]} />);
    expect(screen.queryByRole('slider', { name: '调整抑制等级列宽' })).not.toBeInTheDocument();
    rerender(<ResultsTable {...props} offset={25} />);
    expect(screen.getByRole('slider', { name: '调整抑制等级列宽' })).toHaveAttribute(
      'aria-valuenow',
      '136',
    );
    await userEvent.click(screen.getByRole('button', { name: '来源定位' }));
    expect(props.onJump).toHaveBeenCalledExactlyOnceWith(compound);
    expect(screen.getByLabelText(`选择化合物 ${compound.display_id}`)).toBeChecked();
  });
});
