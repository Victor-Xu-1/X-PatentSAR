import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import type { ActivityColumn, Filters } from '../src/api/types';
import { ColumnMenu } from '../src/features/results/ColumnMenu';
import { resultColumns } from '../src/model/resultColumns';
import type { ResultColumn } from '../src/model/resultColumns';
import { compound } from './fixtures';
import { filterValuesFixture } from './filter-value-fixtures';

const base: Filters = { q: '', confidence: '', review: '', target: '', page: 2, page_size: 25 };
// Captions are view data: derive after the explicit per-test locale is applied.
let compoundColumn: ResultColumn;
const activity: ActivityColumn = {
  id: 'a'.repeat(64),
  ...compound.activities[0]!,
  strength_scale: {
    kind: 'letter',
    direction: 'lower',
    rule: 'letter_grade',
    eligible: 9,
    excluded: 1,
    distinct: 3,
    strong_boundary: 0,
    medium_boundary: 1,
  },
};
let activityColumn: ResultColumn;

function Host({
  initial = base,
  column = compoundColumn,
  catalog,
  onApply = vi.fn(),
}: {
  initial?: Filters;
  column?: typeof compoundColumn;
  catalog?: ActivityColumn;
  onApply?: (patch: Partial<Filters>) => void;
}) {
  const [filters, setFilters] = useState(initial);
  return (
    <ColumnMenu
      projectId="controlled-project"
      column={column}
      activity={catalog}
      filters={filters}
      onFilters={(patch) => {
        onApply(patch);
        setFilters((old) => ({ ...old, ...patch }));
      }}
      onHide={vi.fn()}
    />
  );
}
async function open(name = '原文编号 列选项') {
  await userEvent.click(screen.getByRole('button', { name }));
  await waitFor(() => expect(screen.queryByText('正在加载取值…')).not.toBeInTheDocument());
}
beforeEach(() => {
  compoundColumn = resultColumns()[1]!;
  activityColumn = { ...compoundColumn, id: `activity:${activity.id}`, label: '活性' };
  vi.spyOn(api, 'filterValues').mockImplementation(async (_id, column, _filters, _search, page) =>
    filterValuesFixture(column, undefined, { page }),
  );
});

describe('immediate checklist and committed/cancelled drafts', () => {
  it('requests only the open menu, defaults to all checked, and uses all-minus with independent blank choice', async () => {
    const apply = vi.fn();
    render(<Host onApply={apply} />);
    expect(api.filterValues).not.toHaveBeenCalled();
    await open();
    expect(api.filterValues).toHaveBeenCalledExactlyOnceWith(
      'controlled-project',
      'compound',
      expect.objectContaining({ q: '', page: 1, page_size: 200 }),
      '',
      1,
      expect.any(AbortSignal),
    );
    expect(screen.getByLabelText('筛选值 A')).toBeChecked();
    expect(screen.getByLabelText('全选筛选取值')).toBeChecked();
    expect(screen.queryByLabelText('筛选方式')).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('筛选值 A'));
    expect((screen.getByLabelText('全选筛选取值') as HTMLInputElement).indeterminate).toBe(true);
    await userEvent.click(screen.getByLabelText('筛选值（空白）'));
    expect(apply).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'not_in', values: ['A'], include_empty: false }],
    });
    await open();
    expect(screen.getByLabelText('筛选值 A')).not.toBeChecked();
    expect(screen.getByLabelText('筛选值（空白）')).not.toBeChecked();
    expect(screen.getByLabelText('筛选值 B')).toBeChecked();
  });
  it.each(['取消', 'Escape', 'outside'])(
    'discards changes on %s and restores trigger focus',
    async (method) => {
      const apply = vi.fn();
      render(<Host onApply={apply} />);
      await open();
      await userEvent.click(screen.getByLabelText('筛选值 A'));
      if (method === '取消') await userEvent.click(screen.getByRole('button', { name: '取消' }));
      else if (method === 'Escape') await userEvent.keyboard('{Escape}');
      else fireEvent.pointerDown(document.body);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: '原文编号 列选项' })).toHaveFocus();
      expect(apply).not.toHaveBeenCalled();
      await open();
      expect(screen.getByLabelText('筛选值 A')).toBeChecked();
    },
  );
  it('supports select-none, blanks-only, and global all without serializing the entire vocabulary', async () => {
    const apply = vi.fn();
    render(<Host onApply={apply} />);
    await open();
    await userEvent.click(screen.getByLabelText('全选筛选取值'));
    for (const checkbox of within(screen.getByRole('group', { name: '取值选择' })).getAllByRole(
      'checkbox',
    ))
      expect(checkbox).not.toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'in', values: [], include_empty: false }],
    });
    await open();
    await userEvent.click(screen.getByLabelText('筛选值（空白）'));
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'in', values: [], include_empty: true }],
    });
    await open();
    await userEvent.click(screen.getByLabelText('全选筛选取值'));
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({ page: 1, column_filters: [] });
  });
  it('clears only this column at the top, including when other filters belong to hidden columns', async () => {
    const other = { column: 'property:logP', op: 'gt' as const, value: '1' };
    const apply = vi.fn();
    render(
      <Host
        initial={{ ...base, column_filters: [other, { column: 'compound', op: 'eq', value: 'A' }] }}
        onApply={apply}
      />,
    );
    await open();
    const buttons = within(screen.getByRole('dialog')).getAllByRole('button');
    expect(buttons[0]).toHaveTextContent('清除此列筛选');
    await userEvent.click(buttons[0]!);
    expect(apply).toHaveBeenCalledExactlyOnceWith({ column_filters: [other], page: 1 });
  });
});

describe('list-only search and explicit choice pages', () => {
  it('keeps unchecked choices outside the search and all checked unseen pages when applying a searched draft', async () => {
    vi.mocked(api.filterValues).mockImplementation(async (_id, column, _filters, search, page) =>
      filterValuesFixture(column, search ? ['B'] : ['A', 'B', 'C'], {
        total: search ? 350 : 500,
        page,
      }),
    );
    const apply = vi.fn();
    render(<Host onApply={apply} />);
    await open();
    await userEvent.click(screen.getByLabelText('筛选值 A'));
    fireEvent.change(screen.getByPlaceholderText('搜索仅查找取值'), { target: { value: 'B' } });
    expect(screen.getByRole('button', { name: '确定' })).toBeDisabled();
    expect(apply).not.toHaveBeenCalled();
    expect(await screen.findByLabelText('筛选值 B')).toBeChecked();
    expect(screen.getByLabelText('全选本页匹配取值')).toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'not_in', values: ['A'], include_empty: true }],
    });
  });
  it('retains explicit inclusions across pages and resets choice page, not selections, on search', async () => {
    vi.mocked(api.filterValues).mockImplementation(async (_id, column, _filters, search, page) =>
      filterValuesFixture(column, page === 1 ? ['A', 'B'] : ['C', 'D'], {
        page,
        total: search ? 250 : 336,
      }),
    );
    const apply = vi.fn();
    render(<Host onApply={apply} />);
    await open();
    await userEvent.click(screen.getByLabelText('全选筛选取值'));
    await userEvent.click(screen.getByLabelText('筛选值 A'));
    await userEvent.click(screen.getByRole('button', { name: '下一页取值' }));
    await userEvent.click(await screen.findByLabelText('筛选值 C'));
    fireEvent.change(screen.getByLabelText('查找筛选取值'), { target: { value: 'A' } });
    expect(await screen.findByLabelText('筛选值 A')).toBeChecked();
    expect(api.filterValues).toHaveBeenLastCalledWith(
      'controlled-project',
      'compound',
      expect.any(Object),
      'A',
      1,
      expect.any(AbortSignal),
    );
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'in', values: ['A', 'C'], include_empty: false }],
    });
  });
  it('uses searched select-all only for this page and shows the 201st selection error without silently dropping it', async () => {
    const first = Array.from({ length: 200 }, (_, i) => 'v' + i);
    vi.mocked(api.filterValues).mockImplementation(async (_id, column, _filters, _search, page) =>
      filterValuesFixture(column, page === 1 ? first : ['v200'], {
        page,
        total: 201,
        matching_rows: 500,
      }),
    );
    const apply = vi.fn();
    render(<Host onApply={apply} />);
    await open();
    await userEvent.click(screen.getByLabelText('全选筛选取值'));
    fireEvent.change(screen.getByLabelText('查找筛选取值'), { target: { value: 'v' } });
    await waitFor(() => expect(screen.getByLabelText('全选本页匹配取值')).toBeEnabled());
    await userEvent.click(screen.getByLabelText('全选本页匹配取值'));
    await userEvent.click(screen.getByRole('button', { name: '下一页取值' }));
    const last = await screen.findByLabelText('筛选值 v200');
    expect(last).not.toBeChecked();
    await userEvent.click(last);
    expect(screen.getByRole('alert')).toHaveTextContent('200');
    expect(last).not.toBeChecked();
    expect(screen.getByRole('button', { name: '确定' })).toBeDisabled();
    expect(apply).not.toHaveBeenCalled();
  });
});

describe('conditions, color authority and combined query budgets', () => {
  it('does not silently replace a committed operator when the dominant column type changes', async () => {
    vi.mocked(api.filterValues).mockResolvedValue(
      filterValuesFixture('compound', ['4', '42'], { kind: 'number' }),
    );
    const apply = vi.fn();
    render(
      <Host
        initial={{
          ...base,
          column_filters: [{ column: 'compound', op: 'starts_with', value: '4' }],
        }}
        onApply={apply}
      />,
    );
    await open();
    expect(screen.getByLabelText('筛选方式')).toHaveValue('starts_with');
    expect(screen.getByLabelText('筛选值')).toHaveValue('4');
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(screen.getByRole('alert')).toHaveTextContent('不支持');
    expect(apply).not.toHaveBeenCalled();
    await userEvent.selectOptions(screen.getByLabelText('筛选方式'), 'gte');
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'gte', value: '4' }],
    });
  });
  it('shows one panel at a time, retaining checkbox drafts when returning from conditions or colors', async () => {
    vi.mocked(api.filterValues).mockResolvedValue(
      filterValuesFixture(activityColumn.id, undefined, { bands: [{ value: 'strong', count: 7 }] }),
    );
    render(<Host column={activityColumn} catalog={activity} />);
    await open('活性 列选项');
    expect(screen.queryByRole('button', { name: '选择取值' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('筛选值 A'));
    await userEvent.click(screen.getByRole('button', { name: '文本筛选' }));
    expect(screen.getByLabelText('筛选方式')).toBeVisible();
    expect(screen.queryByLabelText('查找筛选取值')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '按颜色筛选' }));
    expect(screen.queryByLabelText('筛选方式')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('查找筛选取值')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '强档筛选' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '按颜色排序' }));
    expect(screen.queryByRole('button', { name: '强档筛选' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '强档优先' })).toBeVisible();
    expect(screen.queryByLabelText('查找筛选取值')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '选择取值' }));
    expect(screen.getByLabelText('筛选值 A')).not.toBeChecked();
    expect(screen.getByLabelText('筛选值 B')).toBeChecked();
    expect(screen.queryByRole('button', { name: '强档优先' })).not.toBeInTheDocument();
    expect(api.filterValues).toHaveBeenCalledTimes(1);
  });
  it('lets conditions work after choice failure, then explicit retry enables the checklist', async () => {
    vi.mocked(api.filterValues).mockRejectedValueOnce(new Error('choice API offline'));
    const apply = vi.fn();
    render(<Host onApply={apply} />);
    await open();
    expect(screen.getByRole('alert')).toHaveTextContent('choice API offline');
    expect(screen.getByLabelText('筛选值（空白）')).toBeDisabled();
    expect(screen.getByRole('button', { name: '确定' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '文本筛选' }));
    await userEvent.selectOptions(screen.getByLabelText('筛选方式'), 'not_contains');
    fireEvent.change(screen.getByLabelText('筛选值'), { target: { value: 'A' } });
    expect(screen.getByRole('button', { name: '确定' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: '重试取值' }));
    await waitFor(() => expect(screen.queryByText('正在加载取值…')).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: '选择取值' }));
    expect(screen.getByLabelText('筛选值 A')).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: '文本筛选' }));
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [{ column: 'compound', op: 'not_contains', value: 'A' }],
    });
  });
  it('offers numeric comparisons only for numeric columns and presence-only conditions for structures', async () => {
    const number = resultColumns().find((column) => column.id === 'property:molecular_weight')!;
    const { unmount } = render(<Host column={number} />);
    await open('MW 列选项');
    await userEvent.click(screen.getByRole('button', { name: '数字筛选' }));
    expect(screen.getByRole('option', { name: '大于' })).toBeVisible();
    expect(screen.queryByRole('option', { name: '包含' })).not.toBeInTheDocument();
    unmount();
    render(<Host column={resultColumns()[2]!} />);
    await open('结构 列选项');
    expect(screen.getAllByRole('option')).toHaveLength(2);
    expect(screen.getByRole('option', { name: '为空' })).toBeVisible();
    expect(screen.queryByLabelText('查找筛选取值')).not.toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
  it('replaces same-column value filters with a backend band and preserves other columns', async () => {
    vi.mocked(api.filterValues).mockResolvedValue(
      filterValuesFixture(activityColumn.id, undefined, {
        bands: [
          { value: 'strong', count: 7 },
          { value: 'medium', count: 4 },
          { value: 'none', count: 11 },
        ],
      }),
    );
    const other = { column: 'compound', op: 'starts_with' as const, value: '4' };
    const apply = vi.fn();
    render(
      <Host
        column={activityColumn}
        catalog={activity}
        initial={{
          ...base,
          column_filters: [other, { column: activityColumn.id, op: 'in', values: ['A'] }],
        }}
        onApply={apply}
      />,
    );
    await open('活性 列选项');
    await userEvent.click(screen.getByRole('button', { name: '按颜色筛选' }));
    const group = screen.getByRole('group', { name: '按颜色筛选' });
    expect(within(group).getByText('7')).toBeVisible();
    expect(group.querySelector('[data-activity-strength="strong"]')).toBeInTheDocument();
    await userEvent.click(within(group).getByRole('button', { name: '强档筛选' }));
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(apply).toHaveBeenLastCalledWith({
      page: 1,
      column_filters: [other, { column: activityColumn.id, op: 'band', value: 'strong' }],
    });
    await open('活性 列选项');
    expect(screen.getByRole('button', { name: '强档筛选' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
  it('sends requested color-first sort with existing direction and clears it on normal sort', async () => {
    vi.mocked(api.filterValues).mockResolvedValue(
      filterValuesFixture(activityColumn.id, undefined, { bands: [{ value: 'none', count: 11 }] }),
    );
    const apply = vi.fn();
    render(
      <Host
        column={activityColumn}
        catalog={activity}
        initial={{ ...base, sort_column: activityColumn.id, sort_direction: 'desc' }}
        onApply={apply}
      />,
    );
    await open('活性 列选项');
    await userEvent.click(screen.getByRole('button', { name: '按颜色排序' }));
    await userEvent.click(screen.getByRole('button', { name: '无填充优先' }));
    expect(apply).toHaveBeenLastCalledWith({
      sort_column: activityColumn.id,
      sort_direction: 'desc',
      sort_band: 'none',
      page: 1,
    });
    await open('活性 列选项');
    await userEvent.click(screen.getByRole('button', { name: '升序' }));
    expect(apply).toHaveBeenLastCalledWith({
      sort_column: activityColumn.id,
      sort_direction: 'asc',
      sort_band: '',
      page: 1,
    });
  });
  it('makes unknown scales explicit even if the server can count uncolored rows', async () => {
    vi.mocked(api.filterValues).mockResolvedValue(
      filterValuesFixture(activityColumn.id, undefined, { bands: [{ value: 'none', count: 20 }] }),
    );
    render(<Host column={activityColumn} catalog={{ ...activity, strength_scale: null }} />);
    await open('活性 列选项');
    expect(screen.getByText('分档未知，未推断颜色。')).toBeVisible();
    expect(screen.getByRole('button', { name: '按颜色排序' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '按颜色筛选' })).toBeDisabled();
  });
  it('rejects a 21-condition range before callback', async () => {
    const apply = vi.fn();
    render(
      <Host
        column={resultColumns().find((column) => column.id === 'property:molecular_weight')!}
        initial={{
          ...base,
          column_filters: Array.from({ length: 19 }, (_, i) => ({
            column: 'other' + i,
            op: 'eq',
            value: '1',
          })),
        }}
        onApply={apply}
      />,
    );
    await open('MW 列选项');
    await userEvent.click(screen.getByRole('button', { name: '数字筛选' }));
    await userEvent.selectOptions(screen.getByLabelText('筛选方式'), 'range');
    fireEvent.change(screen.getByLabelText('筛选下限'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('筛选上限'), { target: { value: '2' } });
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(screen.getByRole('alert')).toHaveTextContent('20 项或 16 KiB');
    expect(apply).not.toHaveBeenCalled();
  });
  it('rejects a combined UTF-8 payload above 16 KiB, not just above 200 values', async () => {
    const value = '文'.repeat(300);
    vi.mocked(api.filterValues).mockResolvedValue(filterValuesFixture('compound', [value]));
    const apply = vi.fn();
    render(
      <Host
        initial={{
          ...base,
          column_filters: Array.from({ length: 16 }, (_, i) => ({
            column: 'other' + i,
            op: 'eq',
            value: 'x'.repeat(970),
          })),
        }}
        onApply={apply}
      />,
    );
    await open();
    await userEvent.click(screen.getByLabelText('筛选值 ' + value));
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(screen.getByRole('alert')).toHaveTextContent('16 KiB');
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeVisible();
  });
});
