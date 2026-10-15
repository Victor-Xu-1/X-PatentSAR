import type { Atom, Region } from '../../../api/sarTypes';

export interface RegionPointerChoice {
  region: Region;
  order: number;
}
export interface RegionPointerTarget {
  atom: Atom;
  choices: RegionPointerChoice[];
}

// Presentation membership only: original atom identities/coordinates and saved
// region proofs remain untouched. A shared atom has one physical hit target.
export function regionPointerTargets(
  atoms: readonly Atom[],
  regions: readonly Region[],
): RegionPointerTarget[] {
  const targets = atoms.map((atom) => ({ atom, choices: [] as RegionPointerChoice[] }));
  const byIndex = new Map(targets.map((target) => [target.atom.index, target]));
  regions.forEach((region, order) => {
    const indices = new Set(region.atom_indices);
    if (region.hydrogen_anchor != null) indices.add(region.hydrogen_anchor);
    for (const index of indices) byIndex.get(index)?.choices.push({ region, order });
  });
  return targets.filter((target) => target.choices.length > 0);
}

// CSS-pixel hit ownership, not a chemical similarity or identity decision.
// Indistinguishable points retain their complete choices instead of z-order wins.
export function closestRegionTargets(
  targets: readonly RegionPointerTarget[],
  bounds: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
  clientX: number,
  clientY: number,
): RegionPointerTarget[] {
  if (
    bounds.width <= 0 ||
    bounds.height <= 0 ||
    ![bounds.left, bounds.top, bounds.width, bounds.height, clientX, clientY].every(Number.isFinite)
  )
    return [];
  const distances = targets.map((target) =>
    Math.hypot(
      bounds.left + target.atom.x * bounds.width - clientX,
      bounds.top + target.atom.y * bounds.height - clientY,
    ),
  );
  const minimum = distances.reduce((lowest, distance) => Math.min(lowest, distance), Infinity);
  return targets.filter((_, index) => distances[index]! - minimum <= 0.5);
}

export function regionPointerChoices(
  targets: readonly RegionPointerTarget[],
): RegionPointerChoice[] {
  const choices = new Map<string, RegionPointerChoice>();
  for (const target of targets)
    for (const choice of target.choices)
      if (!choices.has(choice.region.id)) choices.set(choice.region.id, choice);
  return [...choices.values()].sort((left, right) => left.order - right.order);
}
