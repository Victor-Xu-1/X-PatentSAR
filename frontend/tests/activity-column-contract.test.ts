import { describe, expect, it } from 'vitest';
import { decodeResults } from '../src/api/decoders';
import { activityContextKey, decodeActivityColumns } from '../src/api/activityColumnDecoders';
import { results, compound } from './fixtures';
const column = {
  id: 'a'.repeat(64),
  name: compound.activities[0]!.name,
  unit: compound.activities[0]!.unit,
  target: compound.activities[0]!.target,
  assay: compound.activities[0]!.assay,
};
describe('project-wide activity columns are explicit, bounded observations', () => {
  it('keeps omitted legacy catalogs unknown and accepts actual complete catalog', () => {
    expect(decodeResults(results).activity_columns).toBeUndefined();
    expect(decodeResults({ ...results, activity_columns: [column] }).activity_columns).toEqual([
      column,
    ]);
  });
  it('rejects duplicate IDs, duplicate contexts, malformed metadata and vocabulary overflow', () => {
    for (const packet of [
      null,
      [{ ...column, id: 'bad' }],
      [column, column],
      [column, { ...column, id: 'b'.repeat(64) }],
      [{ ...column, unit: 4 }],
      Array.from({ length: 1001 }, () => column),
    ])
      expect(() => decodeActivityColumns(packet)).toThrow();
  });
  it('keeps different units/targets/assays separate and does not hide an uncataloged measurement', () => {
    const contexts = [
      column,
      { ...column, id: 'b'.repeat(64), unit: 'nM' },
      { ...column, id: 'c'.repeat(64), target: 'Another target' },
      { ...column, id: 'd'.repeat(64), assay: 'Another assay' },
    ];
    expect(new Set(contexts.map(activityContextKey)).size).toBe(4);
    expect(decodeActivityColumns(contexts)).toHaveLength(4);
    expect(() => decodeResults({ ...results, activity_columns: [] })).toThrow();
  });
});
