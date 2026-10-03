import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ActivityStrengthScale } from '../src/api/types';
import { decodeCompound } from '../src/api/decoders';
import { decodeActivityColumns } from '../src/api/activityColumnDecoders';
import { activityStrength } from '../src/model/activityStrength';
import { ResultsTable } from '../src/features/results/ResultsTable';
import { compound } from './fixtures';

const scale: ActivityStrengthScale = {
  kind: 'numeric',
  direction: 'lower',
  rule: 'potency',
  eligible: 9,
  excluded: 0,
  distinct: 9,
  strong_boundary: 3,
  medium_boundary: 6,
};
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
const column = { id: 'a'.repeat(64), ...compound.activities[0]!, strength_scale: scale };

describe('project-wide activity colors consume authoritative scores, never local-page ranks', () => {
  it('uses both directions and preserves zero, boundaries and ties', () => {
    expect([0, 3, 4, 6, 7].map((value) => activityStrength(value, scale))).toEqual([
      'strong',
      'strong',
      'medium',
      'medium',
      'none',
    ]);
    const high = { ...scale, direction: 'higher' as const, strong_boundary: 7, medium_boundary: 4 };
    expect([3, 4, 6, 7, 9].map((value) => activityStrength(value, high))).toEqual([
      'none',
      'medium',
      'medium',
      'strong',
      'strong',
    ]);
  });

  it('does not invent a grade from missing, legacy or unknown-direction metadata', () => {
    for (const value of [null, undefined, NaN, Infinity])
      expect(activityStrength(value, scale)).toBe('none');
    expect(activityStrength(1, undefined)).toBe('none');
    expect(
      activityStrength(1, {
        ...scale,
        direction: 'unknown',
        strong_boundary: null,
        medium_boundary: null,
      }),
    ).toBe('none');
  });

  it('retains exact source callbacks and independent repeated observation colors', async () => {
    const props = callbacks();
    const row = {
      ...compound,
      activities: [
        compound.activities[0]!,
        { ...compound.activities[0]!, value: 'a repeated observation', page: 7 },
      ],
      activity_rank_values: [2, 8],
      activity_source_keys: ['b'.repeat(64), 'c'.repeat(64)],
    };
    const { rerender } = render(
      <ResultsTable {...props} rows={[row]} activityColumns={[column]} />,
    );
    const cells = document.querySelectorAll('td.activity-value-column');
    expect(cells).toHaveLength(1);
    expect(cells[0]).not.toHaveAttribute('data-activity-strength');
    expect(
      Array.from(cells[0]!.querySelectorAll('.activity-observation'), (item) =>
        item.getAttribute('data-activity-strength'),
      ),
    ).toEqual(['strong', 'none']);
    await userEvent.click(screen.getByLabelText('I-7 抑制等级 活性来源第 7 页'));
    expect(props.onActivitySource).toHaveBeenCalledExactlyOnceWith(
      row,
      row.activities[1],
      row.activity_source_keys[1],
    );
    rerender(
      <ResultsTable
        {...props}
        rows={[{ ...row, activities: [row.activities[0]!], activity_rank_values: [2] }]}
        activityColumns={[column]}
      />,
    );
    expect(document.querySelector('td.activity-value-column')).toHaveAttribute(
      'data-activity-strength',
      'strong',
    );
    expect(document.querySelector('.prediction-column')).not.toHaveAttribute(
      'data-activity-strength',
    );
  });

  it('keeps empty and censored values uncolored without hiding their actual contents', () => {
    const row = {
      ...compound,
      activities: [{ ...compound.activities[0]!, value: '<10' }],
      activity_rank_values: [null],
    };
    render(<ResultsTable {...callbacks()} rows={[row]} activityColumns={[column]} />);
    expect(document.querySelector('td.activity-value-column')).toHaveAttribute(
      'data-activity-strength',
      'none',
    );
    expect(screen.getByLabelText('I-7 抑制等级 活性来源第 5 页')).toHaveTextContent('<10');
  });

  it('rejects malformed additive scores, alignment, cutoff order and missing profile fields', () => {
    for (const values of [[true], ['2'], [Infinity], [], [1, 2]])
      expect(() => decodeCompound({ ...compound, activity_rank_values: values })).toThrow();
    const valid = { ...column, strength_scale: scale };
    expect(decodeActivityColumns([valid])[0]?.strength_scale).toEqual(scale);
    for (const invalid of [
      { ...scale, strong_boundary: 7 },
      { ...scale, eligible: 1 },
      { ...scale, direction: 'unknown' },
      { ...scale, strong_boundary: Infinity },
      { ...scale, kind: 'unknown' },
    ])
      expect(() => decodeActivityColumns([{ ...valid, strength_scale: invalid }])).toThrow();
    expect(decodeCompound({ ...compound, activity_rank_values: [0] }).activity_rank_values).toEqual(
      [0],
    );
  });
});
