import { describe, expect, it } from 'vitest';
import {
  compileValueSelection,
  restoreValueSelection,
  setSelectedValues,
  valueIsSelected,
} from '../src/model/columnValueSelection';

describe('bounded include/exclude checklist drafts', () => {
  it('starts all checked and excludes only the unchecked raw value, including blanks independently', () => {
    const all = restoreValueSelection('compound', []);
    expect(valueIsSelected(all, '25000')).toBe(true);
    expect(compileValueSelection('compound', all)).toEqual([]);
    const draft = setSelectedValues(all, ['8A'], false);
    expect(compileValueSelection('compound', { ...draft, includeEmpty: false })).toEqual([
      { column: 'compound', op: 'not_in', values: ['8A'], include_empty: false },
    ]);
  });
  it('restores legacy blank defaults, and accepts explicit none or blank-only selection', () => {
    expect(
      restoreValueSelection('compound', [{ column: 'compound', op: 'in', values: [] }]),
    ).toEqual({ mode: 'include', values: [], includeEmpty: false });
    expect(
      restoreValueSelection('compound', [{ column: 'compound', op: 'not_in', values: ['8'] }]),
    ).toEqual({ mode: 'exclude', values: ['8'], includeEmpty: true });
    for (const includeEmpty of [true, false])
      expect(
        compileValueSelection('compound', { mode: 'include', values: [], includeEmpty }),
      ).toEqual([{ column: 'compound', op: 'in', values: [], include_empty: includeEmpty }]);
  });
  it('retains explicit selections across searched pages, never replaces them with the current page', () => {
    const original = { mode: 'include' as const, values: ['8'], includeEmpty: false };
    const next = setSelectedValues(original, ['9', '10'], true);
    expect(next.values).toEqual(['8', '9', '10']);
    expect(original.values).toEqual(['8']);
    expect(setSelectedValues(next, ['9'], false).values).toEqual(['8', '10']);
  });
  it('rejects the 201st inclusion or exclusion without mutating the previous draft', () => {
    for (const mode of ['include', 'exclude'] as const) {
      const draft = {
        mode,
        values: Array.from({ length: 200 }, (_, i) => String(i)),
        includeEmpty: true,
      };
      expect(() => setSelectedValues(draft, ['201'], mode === 'include')).toThrow('200');
      expect(draft.values).toHaveLength(200);
    }
  });
});
