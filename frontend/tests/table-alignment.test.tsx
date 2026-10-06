import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { api } from '../src/api';
import { filterValuesFixture } from './filter-value-fixtures';
import type { ActivityColumn } from '../src/api/types';
import { compound } from './fixtures';

const css = (name: string) =>
  readFileSync(new URL('../src/styles/' + name + '.css', import.meta.url), 'utf8');
const styles = [
  'tokens',
  'base',
  'resizing',
  'results',
  'table',
  'activity-strength',
  'table-interactions',
]
  .map(css)
  .join('\n');
const column: ActivityColumn = {
  id: 'a'.repeat(64),
  ...compound.activities[0]!,
  strength_scale: {
    kind: 'plus',
    direction: 'higher',
    rule: 'plus_grade',
    eligible: 9,
    excluded: 0,
    distinct: 3,
    strong_boundary: 2,
    medium_boundary: 1,
  },
};
const props = () => ({
  projectId: 'controlled-project',
  rows: [compound],
  activityColumns: [column],
  selected: new Set<string>(),
  focusedId: null,
  filters: { q: '', target: '', confidence: '', review: '', page: 3, page_size: 10 },
  onFilters: vi.fn(),
  onHideColumn: vi.fn(),
  onSelect: vi.fn(),
  onSelectPage: vi.fn(),
  onJump: vi.fn(),
  onActivitySource: vi.fn(),
  onCrop: vi.fn(),
  onReview: vi.fn(),
});

describe('one centered result-table style authority', () => {
  it('reserves a readable default Compound heading independently of its resize bounds', () => {
    render(<ResultsTable {...props()} />);
    const header = screen.getByRole('table').querySelector('th.frozen-compound')!;
    expect(header.querySelector('.column-heading')!.textContent).toBe('Compound');
    expect(
      screen.getByRole('slider', { name: '调整Compound列宽' }).getAttribute('aria-valuenow'),
    ).toBe('120');
    expect(
      screen.getByRole('slider', { name: '调整Compound列宽' }).getAttribute('aria-valuemin'),
    ).toBe('88');
  });
  let stylesheet: HTMLStyleElement;
  beforeEach(() => {
    vi.spyOn(api, 'filterValues').mockImplementation(async (_id, column) =>
      filterValuesFixture(column, ['++', '+']),
    );
    stylesheet = document.createElement('style');
    stylesheet.textContent = styles;
    document.head.append(stylesheet);
  });
  afterEach(() => stylesheet.remove());

  it.each(['MW', 'LogP', 'TPSA', 'HBD', 'HBA', 'LogS'])(
    'keeps the short %s heading on one line with room for its column menu',
    (label) => {
      render(<ResultsTable {...props()} />);
      const header = screen.getByRole('columnheader', { name: label });
      const heading = header.querySelector('.column-heading')!;
      expect(getComputedStyle(heading).whiteSpace).toBe('nowrap');
      expect(getComputedStyle(heading).textOverflow).toBe('ellipsis');
      expect(header).toHaveAttribute('title', label);
      expect(screen.getByRole('slider', { name: `调整${label}列宽` })).toHaveAttribute(
        'aria-valuenow',
        '88',
      );
      expect(screen.getByRole('slider', { name: `调整${label}列宽` })).toHaveAttribute(
        'aria-valuemin',
        '64',
      );
    },
  );

  it.each(['compact', 'comfortable'] as const)(
    'centers every header, data cell and nested value in %s density without a number column',
    (density) => {
      render(<ResultsTable {...props()} density={density} />);
      const table = screen.getByRole('table');
      for (const cell of table.querySelectorAll('th, td')) {
        expect(getComputedStyle(cell).textAlign).toBe('center');
        expect(getComputedStyle(cell).verticalAlign).toBe('middle');
      }
      for (const button of table.querySelectorAll('.compound-detail-button, .activity-source'))
        expect(getComputedStyle(button).textAlign).toBe('center');
      for (const checkbox of table.querySelectorAll(
        "th > input[type='checkbox'], td > input[type='checkbox']",
      ))
        expect(getComputedStyle(checkbox).display).toBe('block');
      for (const button of table.querySelectorAll('.column-menu-button')) {
        expect(getComputedStyle(button).alignItems).toBe('center');
        expect(getComputedStyle(button).justifyContent).toBe('center');
      }
      expect(screen.queryByRole('columnheader', { name: '#' })).not.toBeInTheDocument();
      expect(screen.getByRole('slider', { name: '调整Compound列宽' })).toBeEnabled();
      expect(getComputedStyle(table.querySelector('.frozen-compound')!).position).toBe('sticky');
    },
  );

  it('centers unavailable structures and preserves the existing no-activity status text', () => {
    render(
      <ResultsTable
        {...props()}
        rows={[
          {
            ...compound,
            structure_image_url: null,
            record_kind: 'structure_only',
            activities: [],
            flags: [],
          },
        ]}
      />,
    );
    const placeholder = document.querySelector('.image-unavailable')!;
    expect(getComputedStyle(placeholder).alignItems).toBe('center');
    expect(getComputedStyle(placeholder).justifyContent).toBe('center');
    expect(screen.getByText('暂无活性数据')).toBeVisible();
    expect(screen.getByLabelText('抑制等级 该指标无数据')).toHaveTextContent('—');
    expect(screen.getByLabelText('MW 未计算')).toHaveTextContent('—');
  });

  it('centers independent mixed-strength observations without aggregating their values or sources', async () => {
    const callbacks = props();
    const row = {
      ...compound,
      activities: [
        { ...compound.activities[0]!, value: '++', page: 5 },
        { ...compound.activities[0]!, value: '+', page: 7 },
        { ...compound.activities[0]!, value: '—', page: null },
      ],
      activity_rank_values: [2, 1, null],
      activity_source_keys: ['b'.repeat(64), 'c'.repeat(64), 'd'.repeat(64)],
    };
    render(<ResultsTable {...callbacks} rows={[row]} />);
    const cell = document.querySelector('td.activity-value-column')!;
    expect(cell).not.toHaveAttribute('data-activity-strength');
    const observations = Array.from(cell.querySelectorAll('.activity-observation'));
    expect(observations.map((item) => item.getAttribute('data-activity-strength'))).toEqual([
      'strong',
      'medium',
      'none',
    ]);
    for (const observation of observations) {
      const style = getComputedStyle(observation);
      expect(style.alignItems).toBe('center');
      expect(style.justifyContent).toBe('center');
    }
    await userEvent.click(screen.getByLabelText('I-7 抑制等级 活性来源第 7 页'));
    expect(callbacks.onActivitySource).toHaveBeenCalledExactlyOnceWith(
      row,
      row.activities[1],
      row.activity_source_keys[1],
    );
    expect(screen.getByLabelText('I-7 抑制等级 活性来源页码未知')).toBeDisabled();
  });

  it('retains centered empty cells and the real column-menu label, sorting and filter behavior', async () => {
    const callbacks = props();
    render(<ResultsTable {...callbacks} rows={[]} />);
    expect(getComputedStyle(screen.getByRole('cell')).textAlign).toBe('center');
    const name = '抑制等级 · 测试靶点 · 契约隔离实验 列选项';
    const trigger = screen.getByRole('button', { name });
    await userEvent.click(trigger);
    const menu = screen.getByRole('dialog', { name });
    expect(trigger).toHaveAttribute('aria-controls', menu.id);
    await userEvent.click(within(menu).getByRole('button', { name: '降序' }));
    expect(callbacks.onFilters).toHaveBeenLastCalledWith({
      sort_column: `activity:${column.id}`,
      sort_direction: 'desc',
      sort_band: '',
      page: 1,
    });
    await userEvent.click(trigger);
    await screen.findByLabelText('筛选值 +');
    await userEvent.click(screen.getByLabelText('全选筛选取值'));
    await userEvent.click(screen.getByLabelText('筛选值 +'));
    await userEvent.click(screen.getByRole('button', { name: '确定' }));
    expect(callbacks.onFilters).toHaveBeenLastCalledWith({
      column_filters: [
        { column: `activity:${column.id}`, op: 'in', values: ['+'], include_empty: false },
      ],
      page: 1,
    });
    expect(trigger).toHaveFocus();
  });
});

function rgbToken(name: string): number[] {
  const hex = css('tokens').match(new RegExp(`--${name}:\\s*#([\\da-f]{6});`, 'i'))![1]!;
  return [0, 2, 4].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
}
function luminance(rgb: number[]): number {
  const channels = rgb.map((value) => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return channels[0]! * 0.2126 + channels[1]! * 0.7152 + channels[2]! * 0.0722;
}
function contrast(a: number[], b: number[]): number {
  const light = [luminance(a), luminance(b)].sort((first, second) => second - first);
  return (light[0]! + 0.05) / (light[1]! + 0.05);
}

describe('vivid strongest activity and pale middle use one readable palette', () => {
  it('separates the strongest fill from middle and uncolored cells while retaining dark-text contrast', () => {
    const strong = rgbToken('activity-strong-surface');
    const medium = rgbToken('activity-medium-surface');
    expect(strong[1]).toBeGreaterThan(strong[0]!);
    expect(strong[1]).toBeGreaterThan(strong[2]!);
    expect(contrast(strong, medium)).toBeGreaterThanOrEqual(1.5);
    expect(contrast(strong, rgbToken('surface'))).toBeGreaterThanOrEqual(1.5);
    expect(contrast(strong, rgbToken('primary'))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(medium, rgbToken('primary'))).toBeGreaterThanOrEqual(4.5);
  });
});
