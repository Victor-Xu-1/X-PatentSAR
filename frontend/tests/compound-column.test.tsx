import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
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

describe('compound identity is separate from the original structure', () => {
  it('places the original identifier first among data columns and removes the row-number column', () => {
    render(<ResultsTable {...callbacks()} rows={[compound]} />);
    const headers = screen.getAllByRole('columnheader');
    expect(headers.slice(0, 3).map((header) => header.getAttribute('data-column'))).toEqual([
      'select',
      'compound',
      'structure',
    ]);
    expect(screen.getByRole('columnheader', { name: /^原文编号$/ })).toBeVisible();
    expect(screen.getByRole('columnheader', { name: /^结构$/ })).toBeVisible();
    expect(screen.queryByRole('columnheader', { name: /^#$/ })).not.toBeInTheDocument();
    const row = screen.getAllByRole('row')[1]!;
    const cells = within(row).getAllByRole('cell');
    expect(cells[1]).toHaveClass('frozen-compound');
    expect(cells[1]).toHaveTextContent(compound.display_id);
    expect(within(cells[1]!).queryByRole('img')).not.toBeInTheDocument();
    expect(cells[2]).toHaveClass('frozen-structure');
    expect(within(cells[2]!).getByRole('img')).toHaveAttribute('src', compound.structure_image_url);
    expect(cells[2]).not.toHaveTextContent(compound.display_id);
    expect(row.querySelector('.row-number')).toBeNull();
  });

  it('keeps the original row identity for selection, details, crop and correction', async () => {
    const props = callbacks();
    render(<ResultsTable {...props} rows={[compound]} />);
    await userEvent.click(screen.getByLabelText(`选择化合物 ${compound.display_id}`));
    await userEvent.click(screen.getByLabelText(`查看 ${compound.display_id} 结构详情`));
    await userEvent.click(screen.getByLabelText(`放大 ${compound.display_id} 结构裁图`));
    await userEvent.click(screen.getByLabelText(`修正 ${compound.display_id}`));
    expect(props.onSelect).toHaveBeenCalledExactlyOnceWith(compound.id);
    expect(props.onCrop.mock.calls).toEqual([[compound], [compound]]);
    expect(props.onReview).toHaveBeenCalledExactlyOnceWith(compound);
    expect(screen.getByRole('table').querySelector('tbody tr')).toHaveAttribute(
      'data-compound',
      compound.id,
    );
  });

  it('retains the full supplied identifier without manufacturing a sequential number', () => {
    const row = { ...compound, id: 'source-record', display_id: 'Compound 8B / long identifier' };
    render(<ResultsTable {...callbacks()} rows={[row]} />);
    const identifier = screen.getByLabelText(`查看 ${row.display_id} 结构详情`);
    expect(identifier).toHaveTextContent(row.display_id);
    expect(identifier.closest('td')).toHaveClass('frozen-compound');
    expect(screen.queryByText(/^1$/)).not.toBeInTheDocument();
  });
});
