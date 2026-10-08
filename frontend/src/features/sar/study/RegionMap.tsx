import type { Atom, Region } from '../../../api/sarTypes';
const colors = [
  '#137e78',
  '#466ca4',
  '#a17421',
  '#865ba3',
  '#407b3a',
  '#a05166',
  '#286c88',
  '#796537',
  '#685bb0',
  '#447768',
  '#967249',
  '#8b586b',
];
export function RegionMap({ atoms, regions }: { atoms: Atom[]; regions: Region[] }) {
  return (
    <div className="sar-region-map" aria-hidden="true">
      {regions.flatMap((region, order) =>
        atoms
          .filter((atom) => region.atom_indices.includes(atom.index))
          .map((atom) => (
            <span
              className="sar-region-mark"
              key={region.id + ':' + atom.index}
              title={region.name ?? 'R' + (order + 1)}
              style={{
                left: atom.x * 100 + '%',
                top: atom.y * 100 + '%',
                borderColor: colors[order % colors.length],
                width: 34 + order * 2,
                height: 34 + order * 2,
              }}
            />
          )),
      )}
    </div>
  );
}
export function RegionLegend({ regions }: { regions: Region[] }) {
  return (
    <ul className="sar-region-legend">
      {regions.map((region, order) => (
        <li key={region.id}>
          <span style={{ background: colors[order % colors.length] }} />
          {region.name ?? 'R' + (order + 1)}
        </li>
      ))}
    </ul>
  );
}
