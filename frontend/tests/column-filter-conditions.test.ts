import { describe, expect, it } from 'vitest';
import {
  columnFilterDraft,
  columnFilterModes,
  compileColumnFilter,
  replaceColumnFilters,
} from '../src/model/columnFilters';
import type { ColumnFilter } from '../src/api/types';

describe('typed conditions and one bounded combined query', () => {
  it('keeps text, number and presence menus distinct', () => {
    expect(columnFilterModes('text')).toEqual([
      'contains',
      'not_contains',
      'starts_with',
      'ends_with',
      'eq',
      'ne',
      'empty',
      'not_empty',
    ]);
    expect(columnFilterModes('number')).toEqual([
      'eq',
      'ne',
      'gt',
      'gte',
      'lt',
      'lte',
      'range',
      'empty',
      'not_empty',
    ]);
    expect(columnFilterModes('presence')).toEqual(['empty', 'not_empty']);
  });
  it('restores range drafts and does not reinterpret censored checklist strings as scalars', () => {
    const range: ColumnFilter[] = [
      { column: 'property:logP', op: 'gte', value: '1' },
      { column: 'property:logP', op: 'lte', value: '3' },
    ];
    const draft = columnFilterDraft('property:logP', range, 'eq');
    expect(draft).toEqual({ op: 'range', value: '1', upper: '3' });
    expect(compileColumnFilter('property:logP', draft, 'number')).toEqual(range);
    for (const value of ['<10', '1–3', 'A', 'NaN', 'Infinity'])
      expect(() =>
        compileColumnFilter('activity:numeric', { op: 'ne', value, upper: '' }, 'number'),
      ).toThrow('有限数值');
    expect(
      compileColumnFilter('compound', { op: 'ends_with', value: 'A', upper: '' }, 'text'),
    ).toEqual([{ column: 'compound', op: 'ends_with', value: 'A' }]);
  });
  it('allows exactly 20 combined conditions, replaces only the owned column, and rejects 21', () => {
    const other: ColumnFilter[] = Array.from({ length: 19 }, (_, i) => ({
      column: 'other' + i,
      op: 'eq',
      value: '1',
    }));
    const own: ColumnFilter = { column: 'compound', op: 'eq', value: 'A' };
    expect(replaceColumnFilters([...other, own], 'compound', [{ ...own, op: 'ne' }])).toHaveLength(
      20,
    );
    expect(() =>
      replaceColumnFilters(other, 'property:logP', [
        { column: 'property:logP', op: 'gte', value: '1' },
        { column: 'property:logP', op: 'lte', value: '2' },
      ]),
    ).toThrow('20');
    expect(other).toHaveLength(19);
  });
  it('accepts exactly 16 KiB combined UTF-8 JSON and rejects another byte', () => {
    const fields: ColumnFilter[] = Array.from({ length: 17 }, (_, i) => ({
      column: 'other' + i,
      op: 'eq',
      value: 'x'.repeat(900),
    }));
    const last: ColumnFilter = { column: 'compound', op: 'eq', value: '' };
    last.value = 'x'.repeat(
      16384 - new TextEncoder().encode(JSON.stringify([...fields, last])).byteLength,
    );
    expect(last.value.length).toBeLessThanOrEqual(1000);
    expect(replaceColumnFilters(fields, 'compound', [last])).toHaveLength(18);
    expect(() =>
      replaceColumnFilters(fields, 'compound', [{ ...last, value: last.value + 'x' }]),
    ).toThrow('16 KiB');
  });
});
