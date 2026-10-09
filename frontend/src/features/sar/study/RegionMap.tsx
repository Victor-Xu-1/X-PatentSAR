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
    <svg className="sar-region-map" viewBox="0 0 1000 800" aria-hidden="true">
      {regions.map((region, order) => {
        const selected = atoms.filter((atom) => region.atom_indices.includes(atom.index));
        if (!selected.length) return null;
        const color = colors[order % colors.length];
        const x = selected.reduce((sum, atom) => sum + atom.x, 0) / selected.length;
        const y = Math.min(...selected.map((atom) => atom.y));
        return (
          <g key={region.id}>
            {selected.map((atom) => (
              <circle
                key={atom.index}
                cx={atom.x * 1000}
                cy={atom.y * 800}
                r="12"
                fill={color}
                fillOpacity=".1"
                stroke={color}
                strokeWidth="1.5"
              />
            ))}
            <text
              x={Math.max(24, Math.min(960, x * 1000))}
              y={Math.max(24, y * 800 - 25)}
              fill={color}
              fontSize="20"
              fontWeight="600"
              textAnchor="middle"
            >
              R{order + 1}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
export function RegionLegend({ regions }: { regions: Region[] }) {
  return (
    <ul className="sar-region-legend">
      {regions.map((region, order) => (
        <li key={region.id}>
          <span style={{ background: colors[order % colors.length] }} />R{order + 1} ·{' '}
          {region.name ?? 'R' + (order + 1)}
        </li>
      ))}
    </ul>
  );
}
