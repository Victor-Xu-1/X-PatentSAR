import { describe, expect, it } from 'vitest';
import { compactNetworkSites } from '../src/features/sar/study/networkSites';
import { studyReport } from './sar-fixtures';
import type { StudyRegionSummary } from '../src/api/sarStudyTypes';
import { regionLabels } from '../src/features/sar/study/regionLabels';

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
  it('keeps distinct hydrogen anchors and only folds the broader containing region with identical comparisons', () => {
    const one = {
      ...site('h1', [], ['a']),
      region: { ...site('h1', [], ['a']).region, hydrogen_anchor: 1 },
    };
    const other = {
      ...site('h2', [], ['a']),
      region: { ...site('h2', [], ['a']).region, hydrogen_anchor: 3 },
    };
    const whole = site('whole', [1, 2], ['a']);
    const distinct = site('distinct', [1, 2], ['a', 'b']);
    expect(compactNetworkSites([one, other, whole, distinct])).toEqual([one, other, distinct]);
  });
  it('separates colocated region labels while preserving chemical anchors and original site order', () => {
    const atoms = [{ index: 0, x: 0.5, y: 0.3, element: 'C' }];
    const regions = Array.from({ length: 10 }, (_, i) => site('region-' + i, [0], ['a']).region);
    const original = JSON.stringify([atoms, regions]);
    const labels = regionLabels(atoms, regions);
    expect(labels).toHaveLength(10);
    for (const [index, label] of labels.entries()) {
      expect(label.order).toBe(index);
      expect(label.anchorX).toBe(500);
      expect(label.anchorY).toBe(240);
      expect(label.x).toBeGreaterThanOrEqual(32);
      expect(label.x).toBeLessThanOrEqual(968);
      expect(label.y).toBeGreaterThanOrEqual(28);
      expect(label.y).toBeLessThanOrEqual(772);
      for (const other of labels.slice(index + 1))
        expect(Math.abs(label.x - other.x) >= 60 || Math.abs(label.y - other.y) >= 34).toBe(true);
    }
    expect(regionLabels(atoms, regions)).toEqual(labels);
    expect(JSON.stringify([atoms, regions])).toBe(original);
    expect(regionLabels(atoms, [site('unknown-atom', [99], ['a']).region])).toEqual([]);
  });
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
