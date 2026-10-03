import { describe, expect, it } from 'vitest';
import { decodeCompound, decodeProject, decodeResults } from '../src/api/decoders';
import { ContractError } from '../src/api/validation';
import { compound, project, results } from './fixtures';

describe('explicit result record kinds', () => {
  it.each(['structure_activity', 'structure_only', 'activity_only'])(
    'retains the backend-provided %s classification',
    (record_kind) => {
      expect(decodeCompound({ ...compound, record_kind }).record_kind).toBe(record_kind);
    },
  );

  it.each(['unknown', 'inactive', false, 4])('rejects invalid record kind %s', (value) => {
    expect(() => decodeCompound({ ...compound, record_kind: value })).toThrow(ContractError);
  });

  it('does not infer a legacy classification from activity or image presence', () => {
    expect(decodeCompound(compound)).not.toHaveProperty('record_kind');
    expect(decodeCompound({ ...compound, activities: [] })).not.toHaveProperty('record_kind');
    expect(
      decodeCompound({ ...compound, structure_id: null, structure_image_url: null }),
    ).not.toHaveProperty('record_kind');
  });

  it('preserves an explicit null classification without guessing the record type', () => {
    expect(decodeCompound({ ...compound, record_kind: null }).record_kind).toBeNull();
  });

  it('keeps the complete union of matched, structure-only and activity-only records', () => {
    const items = [
      { ...compound, id: 'matched', record_kind: 'structure_activity' },
      { ...compound, id: 'structure', record_kind: 'structure_only', activities: [] },
      {
        ...compound,
        id: 'activity',
        record_kind: 'activity_only',
        structure_id: null,
        structure_image_url: null,
      },
    ];
    const decoded = decodeResults({ ...results, items, total: 3 });
    expect(decoded.items.map((item) => item.id)).toEqual(['matched', 'structure', 'activity']);
    expect(decoded.items.map((item) => item.record_kind)).toEqual([
      'structure_activity',
      'structure_only',
      'activity_only',
    ]);
    expect(decoded.items[1]?.activities).toEqual([]);
    expect(decoded.items[2]?.activities).toEqual(compound.activities);
    expect(decoded.total).toBe(3);
  });
});

describe('source-provided coverage counts', () => {
  it('preserves counts including zero without changing the existing summary', () => {
    const summary = { ...project.summary, structure_only: 9, activity_only: 0 };
    expect(decodeProject({ ...project, summary }).summary).toEqual(summary);
  });

  it('preserves null and omitted counts rather than inventing coverage from other totals', () => {
    expect(decodeProject(project).summary).not.toHaveProperty('structure_only');
    expect(decodeProject(project).summary).not.toHaveProperty('activity_only');
    const decoded = decodeProject({
      ...project,
      summary: { ...project.summary, structure_only: null },
    });
    expect(decoded.summary.structure_only).toBeNull();
    expect(decoded.summary).not.toHaveProperty('activity_only');
  });

  it.each(['structure_only', 'activity_only'])('validates %s as a nonnegative count', (key) => {
    for (const value of [-1, 1.5, NaN, Infinity, true, '2']) {
      expect(() =>
        decodeProject({ ...project, summary: { ...project.summary, [key]: value } }),
      ).toThrow(ContractError);
    }
  });

  it('retains the independently supplied first structure page alongside coverage', () => {
    const decoded = decodeProject({
      ...project,
      first_structure_page: 4,
      summary: { ...project.summary, structure_only: 9, activity_only: 2 },
    });
    expect(decoded.first_structure_page).toBe(4);
    expect(decoded.summary.structure_only).toBe(9);
    expect(decoded.summary.activity_only).toBe(2);
  });
});
