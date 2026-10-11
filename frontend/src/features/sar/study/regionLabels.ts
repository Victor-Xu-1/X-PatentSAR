import type { Atom, Region } from '../../../api/sarTypes';

/** Drawing-only displacement; immutable atom indices and site order never change. */
export function regionLabels(atoms: Atom[], regions: Region[]) {
  const placed: { x: number; y: number; anchorX: number; anchorY: number; order: number }[] = [];
  for (const [order, region] of regions.entries()) {
    const selected = atoms.filter((atom) => region.atom_indices.includes(atom.index));
    if (!selected.length) continue;
    const anchorX = (1000 * selected.reduce((sum, atom) => sum + atom.x, 0)) / selected.length;
    const anchorY = 800 * Math.min(...selected.map((atom) => atom.y));
    const ideal = { x: Math.max(32, Math.min(968, anchorX)), y: Math.max(28, anchorY - 32) };
    const candidates = [];
    for (let row = -8; row <= 8; row++)
      for (let column = -8; column <= 8; column++) {
        const x = ideal.x + column * 64,
          y = ideal.y + row * 38;
        if (x >= 32 && x <= 968 && y >= 28 && y <= 772)
          candidates.push({ x, y, distance: column * column * 4096 + row * row * 1444 });
      }
    candidates.sort((a, b) => a.distance - b.distance || a.y - b.y || a.x - b.x);
    const location =
      candidates.find((candidate) =>
        placed.every(
          (label) => Math.abs(label.x - candidate.x) >= 60 || Math.abs(label.y - candidate.y) >= 34,
        ),
      ) ?? ideal;
    placed.push({ x: location.x, y: location.y, anchorX, anchorY, order });
  }
  return placed;
}
