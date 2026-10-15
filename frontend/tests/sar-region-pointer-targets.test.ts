import { expect, it } from 'vitest';
import {
  closestRegionTargets,
  regionPointerChoices,
  regionPointerTargets,
} from '../src/features/sar/study/regionPointerTargets';
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

it('uses displayed pixel geometry rather than data order in a moved non-square frame', () => {
  const targets = regionPointerTargets(atoms, [{ ...namedRegion, atom_indices: [91, 3] }]);
  const original = JSON.stringify(targets);
  const bounds = { left: 37, top: 53, width: 1200, height: 400 };
  expect(
    closestRegionTargets(targets, bounds, 877, 173).map((target) => target.atom.index),
  ).toEqual([91]);
  expect(
    closestRegionTargets(targets, bounds, 277, 373).map((target) => target.atom.index),
  ).toEqual([3]);
  expect(JSON.stringify(targets)).toBe(original);
});

it('retains indistinguishable points and deduplicates only identical recorded choice IDs', () => {
  const near = atoms.map((atom) => ({ ...atom, x: 0.5, y: 0.5 }));
  const regions = [
    { ...namedRegion, id: 'both', atom_indices: [91, 3] },
    { ...namedRegion, id: 'second', atom_indices: [3] },
  ];
  const targets = regionPointerTargets(near, regions);
  const hit = closestRegionTargets(targets, { left: 0, top: 0, width: 100, height: 80 }, 50, 40);
  expect(hit.map((target) => target.atom.index)).toEqual([91, 3]);
  expect(regionPointerChoices(hit).map((choice) => [choice.region.id, choice.order])).toEqual([
    ['both', 0],
    ['second', 1],
  ]);
});

it('does not manufacture a hit for a missing frame, empty source or invalid pointer', () => {
  const targets = regionPointerTargets(atoms, [{ ...namedRegion, atom_indices: [91] }]);
  const bounds = { left: 0, top: 0, width: 100, height: 80 };
  expect(closestRegionTargets([], bounds, 70, 24)).toEqual([]);
  expect(closestRegionTargets(targets, { ...bounds, width: 0 }, 70, 24)).toEqual([]);
  expect(closestRegionTargets(targets, bounds, NaN, 24)).toEqual([]);
  expect(closestRegionTargets(targets, { ...bounds, top: Infinity }, 70, 24)).toEqual([]);
});
