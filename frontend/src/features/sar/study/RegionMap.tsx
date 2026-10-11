import type { Atom, Region } from '../../../api/sarTypes';
import { useRef, useState } from 'react';
import { useInlineSelection } from '../../../components/useInlineSelection';
import { regionLabels } from './regionLabels';
import { regionMarker } from './regionMarker';
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
  const [hovered, setHovered] = useState('');
  if (!regions.length || !atoms.length) return null;
  const dense = regions.length > 8;
  const hasSelection = regions.some((region) => region.id === selected);
  const visibleRegions = dense
    ? regions.filter(
        (region, index) =>
          region.id === selected ||
          region.id === hovered ||
          (!hasSelection && !hovered && index === 0),
      )
    : regions;
  const markers = regions.map(regionMarker);
  const labels = regionLabels(
    atoms,
    visibleRegions,
    visibleRegions.map((region) => markers[regions.indexOf(region)]!.caption),
  ).map((label) => ({
    ...label,
    order: regions.indexOf(visibleRegions[label.order]!),
  }));
  return (
    <>
      <svg className="sar-region-map" viewBox="0 0 1000 800" aria-hidden="true">
        {regions.map((region, order) => {
          if (dense && !visibleRegions.includes(region)) return null;
          const regionAtoms = atoms.filter(
            (atom) =>
              region.atom_indices.includes(atom.index) || atom.index === region.hydrogen_anchor,
          );
          if (!regionAtoms.length) return null;
          const isSelected = selected === region.id;
          const color = colors[order % colors.length];
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
                  strokeDasharray={region.hydrogen_anchor == null ? undefined : '4 3'}
                />
              ))}
            </g>
          );
        })}
        {labels.map(({ x, y, anchorX, anchorY, order, width }) => (
          <g
            key={regions[order]!.id}
            className="sar-region-label"
            data-region-id={regions[order]!.id}
          >
            <line
              x1={anchorX}
              y1={anchorY}
              x2={x}
              y2={y}
              stroke={colors[order % colors.length]}
              strokeWidth="1.5"
            />
            <rect
              x={x - width / 2}
              y={y - 15}
              width={width}
              height="30"
              rx="5"
              fill="var(--surface)"
              fillOpacity="0.95"
            />
            <text
              x={x}
              y={y + 7}
              fill="var(--ink)"
              fontSize="22"
              fontWeight="600"
              textAnchor="middle"
            >
              {markers[order]!.caption}
            </text>
          </g>
        ))}
      </svg>
      {onSelect && (
        <div className="sar-region-hotspots">
          {regions.flatMap((region, order) =>
            atoms
              .filter(
                (atom) =>
                  region.atom_indices.includes(atom.index) || atom.index === region.hydrogen_anchor,
              )
              .map((atom) => (
                <button
                  type="button"
                  // The adjacent named legend is the single keyboard route.
                  // Every atom remains a pointer target, without duplicate Tab stops.
                  tabIndex={-1}
                  key={region.id + ':' + atom.index}
                  aria-label={
                    markers[order]!.caption +
                    ' · ' +
                    region.name +
                    ' · ' +
                    atom.element +
                    ' ' +
                    atom.index
                  }
                  aria-pressed={selected === region.id}
                  onClick={() => onSelect(region.id)}
                  onMouseEnter={() => setHovered(region.id)}
                  onMouseLeave={() => setHovered('')}
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
    <ul ref={strip} className="sar-region-legend" data-dense={regions.length > 8 || undefined}>
      {regions.map((region, order) => (
        <li key={region.id}>
          {onSelect ? (
            <button
              type="button"
              aria-pressed={selected === region.id}
              onClick={() => onSelect(region.id)}
            >
              <span style={{ background: colors[order % colors.length] }} />
              {regionMarker(region, order).showAlias && (
                <b aria-hidden="true">{regionMarker(region, order).marker} · </b>
              )}
              {region.name ?? 'R' + (order + 1)}
              {region.hydrogen_anchor == null ? '' : ' · H'}
            </button>
          ) : (
            <>
              <span style={{ background: colors[order % colors.length] }} />
              {regionMarker(region, order).marker} · {region.name ?? 'R' + (order + 1)}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
