import type { Atom, Region } from '../../../api/sarTypes';
import { useRef } from 'react';
import { useInlineSelection } from '../../../components/useInlineSelection';
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
export function RegionMap({
  atoms,
  regions,
  onSelect,
  selected,
}: {
  atoms: Atom[];
  regions: Region[];
  onSelect?: ((id: string) => void) | undefined;
  selected?: string | undefined;
}) {
  if (!regions.length || !atoms.length) return null;
  const hasSelection = regions.some((region) => region.id === selected);
  return (
    <>
      <svg className="sar-region-map" viewBox="0 0 1000 800" aria-hidden="true">
        {regions.map((region, order) => {
          const regionAtoms = atoms.filter((atom) => region.atom_indices.includes(atom.index));
          if (!regionAtoms.length) return null;
          const isSelected = selected === region.id;
          const color = colors[order % colors.length];
          const x = regionAtoms.reduce((sum, atom) => sum + atom.x, 0) / regionAtoms.length;
          const y = Math.min(...regionAtoms.map((atom) => atom.y));
          return (
            <g
              key={region.id}
              data-region-id={region.id}
              data-selected={isSelected || undefined}
              opacity={hasSelection && !isSelected ? 0.7 : 1}
            >
              {regionAtoms.map((atom) => (
                <circle
                  key={atom.index}
                  cx={atom.x * 1000}
                  cy={atom.y * 800}
                  r="12"
                  fill={color}
                  fillOpacity={isSelected ? 0.24 : 0.1}
                  stroke={color}
                  strokeWidth={isSelected ? 3 : 1.5}
                />
              ))}
              <text
                x={Math.max(24, Math.min(960, x * 1000))}
                y={Math.max(24, y * 800 - 25)}
                fill="var(--ink)"
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
      {onSelect && (
        <div className="sar-region-hotspots">
          {regions.flatMap((region, order) =>
            atoms
              .filter((atom) => region.atom_indices.includes(atom.index))
              .map((atom) => (
                <button
                  type="button"
                  // The adjacent named legend is the single keyboard route.
                  // Every atom remains a pointer target, without duplicate Tab stops.
                  tabIndex={-1}
                  key={region.id + ':' + atom.index}
                  aria-label={
                    'R' +
                    (order + 1) +
                    ' · ' +
                    region.name +
                    ' · ' +
                    atom.element +
                    ' ' +
                    atom.index
                  }
                  aria-pressed={selected === region.id}
                  onClick={() => onSelect(region.id)}
                  style={{
                    left: atom.x * 100 + '%',
                    top: atom.y * 100 + '%',
                    color: colors[order % colors.length],
                  }}
                />
              )),
          )}
        </div>
      )}
    </>
  );
}
export function RegionLegend({
  regions,
  onSelect,
  selected,
}: {
  regions: Region[];
  onSelect?: ((id: string) => void) | undefined;
  selected?: string | undefined;
}) {
  const strip = useRef<HTMLUListElement>(null);
  useInlineSelection(strip, 'button[aria-pressed="true"]');
  return (
    <ul ref={strip} className="sar-region-legend">
      {regions.map((region, order) => (
        <li key={region.id}>
          {onSelect ? (
            <button
              type="button"
              aria-pressed={selected === region.id}
              onClick={() => onSelect(region.id)}
            >
              <span style={{ background: colors[order % colors.length] }} />
              {region.name ?? 'R' + (order + 1)}
            </button>
          ) : (
            <>
              <span style={{ background: colors[order % colors.length] }} />R{order + 1} ·{' '}
              {region.name ?? 'R' + (order + 1)}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
