import { expect, it } from 'vitest';
import { regionPointerTargets } from '../src/features/sar/study/regionPointerTargets';
import { namedRegion } from './sar-fixtures';

const atoms = [
  { index: 91, element: 'C', x: 0.7, y: 0.3 },
  { index: 3, element: 'N', x: 0.2, y: 0.8 },
];

it('preserves original nonsequential atom order, coordinates and every region membership', () => {
  const regions = [
    { ...namedRegion, id: 'first', atom_indices: [3, 91, 91], hydrogen_anchor: 91 },
    { ...namedRegion, id: 'second', atom_indices: [91], hydrogen_anchor: null },
    { ...namedRegion, id: 'unlocated', atom_indices: [400], hydrogen_anchor: null },
  ];
  const original = JSON.stringify({ atoms, regions });
  const targets = regionPointerTargets(atoms, regions);
  expect(targets.map((target) => target.atom)).toEqual(atoms);
  expect(targets[0]!.choices.map((choice) => [choice.region.id, choice.order])).toEqual([
    ['first', 0],
    ['second', 1],
  ]);
  expect(targets[1]!.choices.map((choice) => choice.region.id)).toEqual(['first']);
  expect(targets[0]!.atom).toBe(atoms[0]);
  expect(targets[0]!.choices[0]!.region).toBe(regions[0]);
  expect(JSON.stringify({ atoms, regions })).toBe(original);
});

it('creates no coordinate or atom for an absent original observation', () => {
  expect(regionPointerTargets([], [namedRegion])).toEqual([]);
  expect(regionPointerTargets(atoms, [])).toEqual([]);
  expect(
    regionPointerTargets(atoms, [{ ...namedRegion, atom_indices: [7], hydrogen_anchor: 8 }]),
  ).toEqual([]);
});

it('bounds DOM targets to original atoms even when many region definitions overlap', () => {
  const regions = Array.from({ length: 300 }, (_, order) => ({
    ...namedRegion,
    id: 'source-region-' + order,
    atom_indices: [91, 3],
    hydrogen_anchor: null,
  }));
  const targets = regionPointerTargets(atoms, regions);
  expect(targets).toHaveLength(2);
  expect(targets.every((target) => target.choices.length === 300)).toBe(true);
  expect(targets[1]!.choices.map((choice) => choice.region.id)).toEqual(
    regions.map((region) => region.id),
  );
});
