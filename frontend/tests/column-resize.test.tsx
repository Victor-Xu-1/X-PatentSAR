import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { compound } from './fixtures';

function tableProps() {
  return {
    rows: [compound],
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
  it.each([
    ['Compound', 120, 88],
    ['结构', 136, 88],
  ])(
    'resizes the %s column independently without changing selection',
    async (label, initial, min) => {
      const props = tableProps();
      render(<ResultsTable {...props} />);
      expect(screen.getAllByRole('slider')).toHaveLength(
        screen.getAllByRole('columnheader').length,
      );
      const resize = screen.getByRole('slider', { name: `调整${label}列宽` });
      const table = screen.getByRole('table');
      resize.focus();
      await userEvent.keyboard('{ArrowRight}');
      expect(resize).toHaveAttribute('aria-valuenow', String(Number(initial) + 8));
      expect(table).toHaveClass('columns-resized');
      await userEvent.keyboard('{Home}');
      expect(resize).toHaveAttribute('aria-valuenow', String(min));
      await userEvent.keyboard('{End}');
      expect(resize).toHaveAttribute('aria-valuenow', '480');
      fireEvent.doubleClick(resize);
      expect(resize).toHaveAttribute('aria-valuenow', String(initial));
      expect(screen.getByLabelText(`选择化合物 ${compound.display_id}`)).toBeChecked();
      expect(screen.getByTitle('抑制等级 = ++')).toBeVisible();
      expect(props.onSelect).not.toHaveBeenCalled();
      expect(props.onSelectPage).not.toHaveBeenCalled();
    },
  );
  it('starts at measured width and cancels back to the original table', () => {
    const props = tableProps();
    render(<ResultsTable {...props} />);
    const header = screen.getByRole('columnheader', { name: 'Compound' });
    vi.spyOn(header, 'getBoundingClientRect').mockReturnValue({ width: 200 } as DOMRect);
    const resize = screen.getByRole('slider', { name: '调整Compound列宽' });
    fireEvent.pointerDown(resize, { pointerId: 1, button: 0, clientX: 200, isPrimary: true });
    fireEvent.pointerMove(resize, { pointerId: 1, clientX: 290 });
    expect(resize).toHaveAttribute('aria-valuenow', '290');
    fireEvent.keyDown(resize, { key: 'Escape' });
    fireEvent.pointerUp(resize, { pointerId: 1 });
    expect(screen.getByRole('table')).not.toHaveClass('columns-resized');
    expect(resize).toHaveAttribute('aria-valuenow', '120');
    expect(props.onSelect).not.toHaveBeenCalled();
  });
  it('retains widths across pages and metric hiding without changing source navigation', async () => {
    const props = tableProps();
    const { rerender } = render(<ResultsTable {...props} />);
    const resize = screen.getByRole('slider', { name: '调整抑制等级列宽' });
    resize.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(resize).toHaveAttribute('aria-valuenow', '168');
    rerender(<ResultsTable {...props} metrics={[]} />);
    expect(screen.queryByRole('slider', { name: '调整抑制等级列宽' })).not.toBeInTheDocument();
    const next = { ...compound, id: 'I-8', display_id: 'I-8' };
    rerender(<ResultsTable {...props} rows={[next]} selected={new Set([next.id])} />);
    expect(screen.getByRole('slider', { name: '调整抑制等级列宽' })).toHaveAttribute(
      'aria-valuenow',
      '168',
    );
    await userEvent.click(screen.getByRole('button', { name: 'I-8 结构来源第 4 页' }));
    expect(props.onJump).toHaveBeenCalledExactlyOnceWith(next);
    expect(screen.getByLabelText(`选择化合物 ${next.display_id}`)).toBeChecked();
  });
});
