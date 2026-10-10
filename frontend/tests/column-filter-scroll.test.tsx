import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { ColumnValueChecklist } from '../src/features/results/ColumnValueChecklist';
import { filterValuesFixture } from './filter-value-fixtures';

const props = () => ({
  choices: filterValuesFixture('compound', ['I-1', 'I-2']),
  selection: { mode: 'exclude' as const, values: [], includeEmpty: true },
  search: '',
  page: 1,
  disabled: false,
  onSearch: vi.fn(),
  onPage: vi.fn(),
  onChange: vi.fn(),
  onError: vi.fn(),
});

it('contains the semantic value group inside an ordinary bounded scrolling box', () => {
  render(<ColumnValueChecklist {...props()} />);
  const group = screen.getByRole('group', { name: '取值选择' });
  // Fieldset's anonymous content box can escape its own constrained flex height.
  // The native browser test checks clipping/hit testing, not just CSS declarations.
  expect(group.parentElement).toHaveClass('column-value-choices');
  expect(group.parentElement?.tagName).toBe('DIV');
  expect(group).toContainElement(screen.getByLabelText('筛选值 I-1'));
  expect(screen.getByLabelText('筛选值 I-1')).toBeEnabled();
});

it.each(['loading', 'disabled'] as const)(
  'retains inherited disabled semantics while %s',
  (state) => {
    render(
      <ColumnValueChecklist
        {...props()}
        choices={state === 'loading' ? null : props().choices}
        disabled={state === 'disabled'}
      />,
    );
    const group = screen.getByRole('group', { name: '取值选择' });
    expect(group.tagName).toBe('FIELDSET');
    expect(group).toBeDisabled();
    expect(screen.getByLabelText('全选筛选取值')).toBeDisabled();
  },
);
