import { describe, expect, it } from 'vitest';
import { compactNetworkSites } from '../src/features/sar/study/networkSites';
import { studyReport } from './sar-fixtures';
import type { StudyRegionSummary } from '../src/api/sarStudyTypes';

function site(id: string, atoms: number[], members: string[]): StudyRegionSummary {
  const original = studyReport.regions[0]!;
  return {
    ...original,
    origin: 'single_site',
    region: { ...original.region, id, atom_indices: atoms },
    fragments: [
      { ...original.fragments[0]!, molecule_ids: [original.region.molecule_id, ...members] },
    ],
  };
}
describe('compact chemical sites without lost comparisons or scientific rewrites', () => {
  it('keeps the minimal nested interpretation with exactly identical accepted source pairs', () => {
    const small = site('small', [1], ['a', 'b']),
      large = site('large', [1, 2], ['b', 'a']);
    const before = JSON.stringify([small, large]);
    expect(compactNetworkSites([small, large])).toEqual([small]);
    expect(JSON.stringify([small, large])).toBe(before);
  });
  it('keeps unique pairs, distinct positions and explicit manual regions', () => {
    const small = site('small', [1], ['a']),
      expanded = site('expanded', [1, 2], ['a', 'b']);
    const other = site('other', [3], ['a']);
    const manual = { ...site('manual', [1, 2], ['a']), origin: 'manual' as const };
    expect(compactNetworkSites([small, expanded, other, manual])).toEqual([
      small,
      expanded,
      other,
      manual,
    ]);
  });
  it('never collapses regions from a different reference or molecular revision', () => {
    const small = site('small', [1], ['a']),
      large = site('large', [1, 2], ['a']);
    const changed = { ...large, region: { ...large.region, graph_sha256: 'b'.repeat(64) } };
    const other = { ...large, region: { ...large.region, molecule_id: 'another' } };
    expect(compactNetworkSites([small, changed, other])).toEqual([small, changed, other]);
  });
});
